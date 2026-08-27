#include <stdexcept>
#include <thread>

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "tick_parser.hpp"
#include "ring_buffer.hpp"
#include "vwap_engine.hpp"

namespace py = pybind11;

namespace quant {

namespace {

inline bool parse_python_tick(py::handle obj, TickFrame& out) {
    if (py::isinstance<py::bytes>(obj)) {
        py::bytes payload = py::reinterpret_borrow<py::bytes>(obj);
        char* buffer = nullptr;
        Py_ssize_t size = 0;
        if (PyBytes_AsStringAndSize(payload.ptr(), &buffer, &size) < 0) {
            return false;
        }
        if (buffer == nullptr || size < 0) {
            return false;
        }
        return parse_and_validate_tick(buffer, static_cast<std::size_t>(size), out);
    }

    if (!py::isinstance<py::dict>(obj)) {
        return false;
    }

    py::dict payload = py::reinterpret_borrow<py::dict>(obj);

    auto get_value = [&](const char* key) -> py::handle {
        if (!payload.contains(key)) {
            return py::none();
        }
        return payload[key];
    };

    py::handle ts_value = get_value("timestamp_ns");
    if (ts_value.is_none()) {
        ts_value = get_value("timestamp");
    }
    if (ts_value.is_none()) {
        ts_value = get_value("ts");
    }
    if (ts_value.is_none()) {
        return false;
    }

    py::handle price_value = get_value("price");
    if (price_value.is_none()) {
        price_value = get_value("ltp");
    }
    if (price_value.is_none()) {
        price_value = get_value("last_traded_price");
    }
    if (price_value.is_none()) {
        return false;
    }

    py::handle volume_value = get_value("volume");
    if (volume_value.is_none()) {
        volume_value = get_value("qty");
    }
    if (volume_value.is_none()) {
        volume_value = py::int_(0);
    }

    py::handle atr_value = get_value("atr");
    if (atr_value.is_none()) {
        atr_value = get_value("atr_14");
    }
    if (atr_value.is_none()) {
        atr_value = get_value("current_atr");
    }
    if (atr_value.is_none()) {
        atr_value = py::float_(0.0);
    }

    out.timestamp_ns = py::cast<std::int64_t>(ts_value);
    out.price = py::cast<double>(price_value);
    out.volume = py::cast<std::int64_t>(volume_value);
    out.atr = py::cast<double>(atr_value);
    return is_valid_tick(out);
}

}  // namespace

#include <mutex>

class PyQuantEngine {
public:
    PyQuantEngine() : running_(true), consumer_([this]() { consumer_loop(); }) {
    }

    ~PyQuantEngine() {
        running_ = false;
        if (consumer_.joinable()) {
            consumer_.join();
        }
    }

    void push_tick(py::object tick_obj) {
        TickFrame tick{};
        if (!parse_python_tick(tick_obj, tick)) {
            return;
        }
        ring_buffer_.try_push(tick);
    }

    void update_tick(double price, double volume, double current_atr = 0.0) {
        TickFrame tick{};
        tick.timestamp_ns = static_cast<std::int64_t>(
            std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::system_clock::now().time_since_epoch()
            ).count()
        );
        tick.price = price;
        tick.volume = static_cast<std::int64_t>(volume);
        tick.atr = current_atr;
        if (is_valid_tick(tick)) {
            ring_buffer_.try_push(tick);
        }
    }

    void update_tick_full(std::int64_t ts_ns, double price, std::int64_t volume, double current_atr = 0.0) {
        TickFrame tick{};
        tick.timestamp_ns = ts_ns;
        tick.price = price;
        tick.volume = volume;
        tick.atr = current_atr;
        if (is_valid_tick(tick)) {
            ring_buffer_.try_push(tick);
        }
    }

    py::dict snapshot() const {
        std::lock_guard<std::mutex> lock(mtx_);
        const auto candle = engine_.latest_candle();
        const auto signal = engine_.latest_signal();

        py::dict out;
        out["vwap"] = engine_.latest_vwap();
        out["buy_signal"] = signal.buy_signal;
        out["candle_ts_ns"] = candle.ts_ns;
        out["candle_open"] = candle.open;
        out["candle_high"] = candle.high;
        out["candle_low"] = candle.low;
        out["candle_close"] = candle.close;
        out["candle_volume"] = candle.volume;
        out["candle_atr"] = candle.atr;
        return out;
    }

private:
    void consumer_loop() {
        while (running_) {
            TickFrame tick{};
            while (ring_buffer_.try_pop(tick)) {
                std::lock_guard<std::mutex> lock(mtx_);
                engine_.update_tick(tick.timestamp_ns, tick.price, tick.volume, tick.atr);
            }
            std::this_thread::yield();
        }
    }

    mutable std::mutex mtx_;
    std::atomic<bool> running_;
    SPSCQueue<TickFrame, 4096> ring_buffer_;
    VwapEngine engine_;
    std::thread consumer_;
};

}  // namespace quant

PYBIND11_MODULE(libquant_engine, m) {
    m.doc() = "High-performance native quant engine for low-latency tick ingestion and VWAP streaming.";

    py::class_<quant::PyQuantEngine>(m, "PyQuantEngine")
        .def(py::init<>())
        .def("push_tick", &quant::PyQuantEngine::push_tick, py::arg("tick"))
        .def("update_tick", &quant::PyQuantEngine::update_tick,
             py::arg("price"), py::arg("volume"), py::arg("current_atr") = 0.0)
        .def("update_tick_full", &quant::PyQuantEngine::update_tick_full,
             py::arg("ts_ns"), py::arg("price"), py::arg("volume"), py::arg("current_atr") = 0.0)
        .def("snapshot", &quant::PyQuantEngine::snapshot);

    py::class_<quant::VwapEngine>(m, "VwapEngine")
        .def(py::init<>())
        .def("update_tick",
             static_cast<void (quant::VwapEngine::*)(std::int64_t, double, std::int64_t, double)>(&quant::VwapEngine::update_tick),
             py::arg("ts_ns"), py::arg("price"), py::arg("volume"), py::arg("current_atr") = 0.0)
        .def("update_tick",
             static_cast<void (quant::VwapEngine::*)(double, double, double)>(&quant::VwapEngine::update_tick),
             py::arg("price"), py::arg("volume"), py::arg("current_atr") = 0.0)
        .def("latest_vwap", &quant::VwapEngine::latest_vwap)
        .def("latest_candle", &quant::VwapEngine::latest_candle)
        .def("latest_signal", &quant::VwapEngine::latest_signal)
        .def("reset_session", &quant::VwapEngine::reset_session);
}

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
        volume_value = get_value("v");
    }
    if (volume_value.is_none()) {
        volume_value = py::int_(0);
    }

    out.timestamp_ns = py::cast<std::int64_t>(ts_value);
    out.price = py::cast<double>(price_value);
    out.volume = py::cast<std::int64_t>(volume_value);
    return is_valid_tick(out);
}

}  // namespace

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

    py::dict snapshot() const {
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
        return out;
    }

private:
    void consumer_loop() {
        while (running_) {
            TickFrame tick{};
            while (ring_buffer_.try_pop(tick)) {
                engine_.update_tick(tick.timestamp_ns, tick.price, tick.volume);
            }
            std::this_thread::yield();
        }
    }

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
        .def("snapshot", &quant::PyQuantEngine::snapshot);
}

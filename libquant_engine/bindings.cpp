#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include "tick_parser.hpp"
#include "ring_buffer.hpp"
#include "vwap_engine.hpp"

namespace py = pybind11;

namespace quant {

class PyQuantEngine {
public:
    PyQuantEngine() = default;

    void push_tick(py::object tick_obj) {
        // raw python dict-like object expected: {"timestamp_ns": ..., "price": ..., "volume": ...}
        if (!py::hasattr(tick_obj, "__getitem__")) {
            throw std::runtime_error("tick must behave like a dict-like object");
        }

        const auto ts_value = tick_obj["timestamp_ns"];
        const auto price_value = tick_obj["price"];
        const auto vol_value = tick_obj["volume"];

        const std::int64_t ts_ns = py::cast<std::int64_t>(ts_value);
        const double price = py::cast<double>(price_value);
        const std::int64_t volume = py::cast<std::int64_t>(vol_value);

        engine_.update_tick(ts_ns, price, volume);
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
    VwapEngine engine_;
};

}  // namespace quant

PYBIND11_MODULE(libquant_engine, m) {
    m.doc() = "High-performance native quant engine for low-latency tick ingestion and VWAP streaming.";

    py::class_<quant::PyQuantEngine>(m, "PyQuantEngine")
        .def(py::init<>())
        .def("push_tick", &quant::PyQuantEngine::push_tick, py::arg("tick"))
        .def("snapshot", &quant::PyQuantEngine::snapshot);
}

#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace quant {

struct Candle {
    std::int64_t ts_ns;
    double open;
    double high;
    double low;
    double close;
    std::int64_t volume;
};

struct SignalFlags {
    bool trend_confirmed;
    bool low_tests_vwap;
    bool close_bounces_vwap;
    bool buy_signal;
};

class alignas(64) VwapEngine {
public:
    static constexpr std::int64_t kNsPerMinute = 60LL * 1000000000LL;

    VwapEngine() : session_date_(0), session_start_ns_(0), cum_volume_price_(0.0), cum_volume_(0.0) {
        reset_candle();
    }

    void update_tick(std::int64_t ts_ns, double price, std::int64_t volume) {
        if (price <= 0.0 || !std::isfinite(price) || volume <= 0) {
            return;
        }

        const std::int64_t epoch_seconds = ts_ns / 1000000000LL;
        const std::int64_t day = epoch_seconds / 86400LL;
        if (day != current_day_) {
            reset_session();
            current_day_ = day;
        }

        const double tpv = price * static_cast<double>(volume);
        cum_volume_price_ += tpv;
        cum_volume_ += static_cast<double>(volume);

        const double vwap = (cum_volume_ > 0.0) ? cum_volume_price_ / cum_volume_ : 0.0;
        latest_vwap_ = vwap;

        if (ts_ns >= last_tick_ns_ + kNsPerMinute) {
            finalize_candle_locked();
        }

        update_candle_runtime(price, volume, ts_ns);
        last_tick_ns_ = ts_ns;
    }

    void reset_session() {
        cum_volume_price_ = 0.0;
        cum_volume_ = 0.0;
        latest_vwap_ = 0.0;
        reset_candle();
        last_tick_ns_ = 0;
    }

    double latest_vwap() const { return latest_vwap_; }
    Candle latest_candle() const { return latest_candle_; }
    SignalFlags latest_signal() const { return latest_signal_; }

private:
    void finalize_candle_locked() {
        current_candle_.ts_ns = current_candle_start_ns_;
        current_candle_.open = candle_open_;
        current_candle_.high = candle_high_;
        current_candle_.low = candle_low_;
        current_candle_.close = candle_close_;
        current_candle_.volume = candle_volume_;

        latest_candle_ = current_candle_;
        latest_signal_ = evaluate_signal();
        reset_candle();
    }

    void reset_candle() {
        current_candle_ = {};
        candle_open_ = 0.0;
        candle_high_ = -std::numeric_limits<double>::infinity();
        candle_low_ = std::numeric_limits<double>::infinity();
        candle_close_ = 0.0;
        candle_volume_ = 0;
        current_candle_start_ns_ = 0;
    }

    void update_candle_runtime(double price, std::int64_t volume, std::int64_t ts_ns) {
        if (current_candle_start_ns_ == 0) {
            current_candle_start_ns_ = ts_ns;
            candle_open_ = price;
            candle_high_ = price;
            candle_low_ = price;
            candle_close_ = price;
            candle_volume_ = volume;
            return;
        }

        candle_high_ = std::max(candle_high_, price);
        candle_low_ = std::min(candle_low_, price);
        candle_close_ = price;
        candle_volume_ += volume;
    }

    SignalFlags evaluate_signal() const {
        SignalFlags flags{};
        const double vwap = latest_vwap_;
        if (vwap <= 0.0) {
            flags.buy_signal = false;
            return flags;
        }

        const bool low_tests = latest_candle_.low <= (vwap * 1.001);
        const bool close_bounces = latest_candle_.close > vwap;
        flags.low_tests_vwap = low_tests;
        flags.close_bounces_vwap = close_bounces;
        flags.buy_signal = low_tests && close_bounces;
        return flags;
    }

    std::int64_t current_day_ = 0;
    std::int64_t session_start_ns_;
    std::chrono::seconds session_date_{0};
    double cum_volume_price_;
    double cum_volume_;
    double latest_vwap_ = 0.0;
    SignalFlags latest_signal_{};

    Candle latest_candle_{};
    Candle current_candle_{};
    double candle_open_ = 0.0;
    double candle_high_ = 0.0;
    double candle_low_ = 0.0;
    double candle_close_ = 0.0;
    std::int64_t candle_volume_ = 0;
    std::int64_t current_candle_start_ns_ = 0;
    std::int64_t last_tick_ns_ = 0;
};

}  // namespace quant

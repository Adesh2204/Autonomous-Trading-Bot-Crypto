#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <limits>

namespace quant {

struct Candle {
    std::int64_t ts_ns = 0;
    double open = 0.0;
    double high = 0.0;
    double low = 0.0;
    double close = 0.0;
    std::int64_t volume = 0;
    double vwap = 0.0;
};

struct SignalFlags {
    bool trend_confirmed = false;
    bool low_tests_vwap = false;
    bool close_bounces_vwap = false;
    bool buy_signal = false;
};

class alignas(64) VwapEngine {
public:
    static constexpr std::int64_t kNsPerMinute = 60LL * 1000000000LL;

    VwapEngine() : current_day_(0), current_minute_bucket_(0), last_minute_bucket_(-1), cum_volume_price_(0.0), cum_volume_(0.0) {
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

        const std::int64_t minute_bucket = ts_ns / kNsPerMinute;
        if (last_minute_bucket_ >= 0 && minute_bucket > last_minute_bucket_) {
            finalize_candle_locked();
        }

        if (last_minute_bucket_ < 0) {
            start_new_candle(ts_ns, price, volume);
        } else if (minute_bucket == last_minute_bucket_) {
            update_candle_runtime(price, volume);
        } else {
            // Gap across multiple minutes: treat the next minute as a new candle
            // without allowing stale data to leak from the previous bucket.
            start_new_candle(ts_ns, price, volume);
        }

        last_minute_bucket_ = minute_bucket;
        current_minute_bucket_ = minute_bucket;

        const double tpv = price * static_cast<double>(volume);
        cum_volume_price_ += tpv;
        cum_volume_ += static_cast<double>(volume);
        latest_vwap_ = (cum_volume_ > 0.0) ? cum_volume_price_ / cum_volume_ : 0.0;
    }

    void reset_session() {
        cum_volume_price_ = 0.0;
        cum_volume_ = 0.0;
        latest_vwap_ = 0.0;
        recent_closed_.clear();
        reset_candle();
        last_minute_bucket_ = -1;
    }

    double latest_vwap() const { return latest_vwap_; }
    Candle latest_candle() const { return latest_candle_; }
    SignalFlags latest_signal() const { return latest_signal_; }

private:
    void start_new_candle(std::int64_t ts_ns, double price, std::int64_t volume) {
        current_candle_start_ns_ = ts_ns;
        candle_open_ = price;
        candle_high_ = price;
        candle_low_ = price;
        candle_close_ = price;
        candle_volume_ = volume;
    }

    void update_candle_runtime(double price, std::int64_t volume) {
        candle_high_ = std::max(candle_high_, price);
        candle_low_ = std::min(candle_low_, price);
        candle_close_ = price;
        candle_volume_ += volume;
    }

    void finalize_candle_locked() {
        if (current_candle_start_ns_ == 0) {
            return;
        }

        Candle closed{};
        closed.ts_ns = current_candle_start_ns_;
        closed.open = candle_open_;
        closed.high = candle_high_;
        closed.low = candle_low_;
        closed.close = candle_close_;
        closed.volume = candle_volume_;
        closed.vwap = latest_vwap_;

        recent_closed_.push_back(closed);
        if (recent_closed_.size() > 3) {
            recent_closed_.pop_front();
        }

        latest_candle_ = closed;
        latest_signal_ = evaluate_signal();
        reset_candle();
    }

    void reset_candle() {
        current_candle_start_ns_ = 0;
        candle_open_ = 0.0;
        candle_high_ = -std::numeric_limits<double>::infinity();
        candle_low_ = std::numeric_limits<double>::infinity();
        candle_close_ = 0.0;
        candle_volume_ = 0;
    }

    SignalFlags evaluate_signal() const {
        SignalFlags flags{};
        if (recent_closed_.size() < 3) {
            return flags;
        }

        const auto last3 = std::deque<Candle>(recent_closed_.begin(), recent_closed_.end());
        bool all_close_above_vwap = true;
        for (const auto& closed : last3) {
            if (closed.close <= closed.vwap) {
                all_close_above_vwap = false;
                break;
            }
        }
        flags.trend_confirmed = all_close_above_vwap;

        const Candle& current = latest_candle_;
        flags.low_tests_vwap = current.low <= (current.vwap * 1.001);
        flags.close_bounces_vwap = current.close > current.vwap;
        flags.buy_signal = flags.trend_confirmed && flags.low_tests_vwap && flags.close_bounces_vwap;
        return flags;
    }

    std::int64_t current_day_;
    std::int64_t current_minute_bucket_;
    std::int64_t last_minute_bucket_;
    double cum_volume_price_;
    double cum_volume_;
    double latest_vwap_ = 0.0;
    SignalFlags latest_signal_{};
    Candle latest_candle_{};
    std::deque<Candle> recent_closed_;

    std::int64_t current_candle_start_ns_ = 0;
    double candle_open_ = 0.0;
    double candle_high_ = 0.0;
    double candle_low_ = 0.0;
    double candle_close_ = 0.0;
    std::int64_t candle_volume_ = 0;
};

}  // namespace quant

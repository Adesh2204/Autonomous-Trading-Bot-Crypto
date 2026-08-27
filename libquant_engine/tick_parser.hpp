#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <type_traits>

namespace quant {

struct TickFrame {
    std::int64_t timestamp_ns;
    double price;
    std::int64_t volume;
    double atr = 0.0;
};

inline bool is_valid_tick(const TickFrame& tick) {
    return std::isfinite(tick.price) && tick.price > 0.0 && tick.volume > 0;
}

inline TickFrame parse_tick_from_bytes(const void* raw, std::size_t size) {
    // Expected binary layout: 8-byte nanoseconds + 8-byte double + 8-byte int64 volume.
    // This is intentionally strict, compact, and zero-copy friendly.
    TickFrame frame{};
    if (size < sizeof(TickFrame)) {
        frame.price = -1.0;
        frame.volume = 0;
        return frame;
    }

    std::memcpy(&frame, raw, sizeof(TickFrame));
    return frame;
}

inline bool parse_and_validate_tick(const void* raw, std::size_t size, TickFrame& out) {
    out = parse_tick_from_bytes(raw, size);
    return is_valid_tick(out);
}

}  // namespace quant

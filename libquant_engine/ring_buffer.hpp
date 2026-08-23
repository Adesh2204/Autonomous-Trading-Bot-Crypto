#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <new>

namespace quant {

template <typename T, std::size_t Capacity>
class alignas(64) SPSCQueue {
public:
    static_assert((Capacity & (Capacity - 1)) == 0, "Capacity must be a power of two");

    SPSCQueue() : head_(0), tail_(0) {
        for (std::size_t i = 0; i < Capacity; ++i) {
            slots_[i].in_use.store(false, std::memory_order_relaxed);
        }
    }

    bool try_push(const T& value) {
        const std::size_t head = head_.load(std::memory_order_relaxed);
        const std::size_t next = (head + 1) & (Capacity - 1);
        if (next == tail_.load(std::memory_order_acquire)) {
            return false;
        }

        slots_[head].value = value;
        slots_[head].in_use.store(true, std::memory_order_release);
        head_.store(next, std::memory_order_release);
        return true;
    }

    bool try_pop(T& out) {
        const std::size_t tail = tail_.load(std::memory_order_relaxed);
        if (!slots_[tail].in_use.load(std::memory_order_acquire)) {
            return false;
        }

        out = slots_[tail].value;
        slots_[tail].in_use.store(false, std::memory_order_release);
        tail_.store((tail + 1) & (Capacity - 1), std::memory_order_release);
        return true;
    }

    bool empty() const {
        return head_.load(std::memory_order_acquire) == tail_.load(std::memory_order_acquire);
    }

private:
    struct alignas(64) Slot {
        T value{};
        std::atomic<bool> in_use;
    };

    alignas(64) std::atomic<std::size_t> head_;
    alignas(64) std::atomic<std::size_t> tail_;
    Slot slots_[Capacity];
};

}  // namespace quant

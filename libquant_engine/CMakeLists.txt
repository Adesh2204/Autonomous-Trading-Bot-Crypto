cmake_minimum_required(VERSION 3.18)
project(libquant_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(pybind11 REQUIRED)

add_library(libquant_engine MODULE bindings.cpp)

target_include_directories(libquant_engine PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(libquant_engine PRIVATE pybind11::module)

if(MSVC)
    target_compile_options(libquant_engine PRIVATE /O2 /GL)
else()
    target_compile_options(libquant_engine PRIVATE -O3 -march=native -flto)
endif()

set_target_properties(libquant_engine PROPERTIES PREFIX "")
set_target_properties(libquant_engine PROPERTIES OUTPUT_NAME "libquant_engine")

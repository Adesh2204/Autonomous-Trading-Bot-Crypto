cmake_minimum_required(VERSION 3.18)
project(libquant_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)

execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import pybind11; print(pybind11.get_cmake_dir())"
    OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

if(NOT PYBIND11_CMAKE_DIR)
    message(FATAL_ERROR "pybind11 is not installed in the active Python environment. Install it with: ./.venv/bin/python -m pip install pybind11")
endif()

set(pybind11_DIR "${PYBIND11_CMAKE_DIR}" CACHE PATH "pybind11 CMake directory" FORCE)
find_package(pybind11 CONFIG REQUIRED)

add_library(libquant_engine MODULE bindings.cpp)

target_include_directories(libquant_engine PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(libquant_engine PRIVATE pybind11::module)

target_compile_features(libquant_engine PRIVATE cxx_std_20)

if(MSVC)
    target_compile_options(libquant_engine PRIVATE /O2 /GL)
else()
    target_compile_options(libquant_engine PRIVATE -O3 -march=native -flto)
endif()

set_target_properties(libquant_engine PROPERTIES PREFIX "")
set_target_properties(libquant_engine PROPERTIES OUTPUT_NAME "libquant_engine")

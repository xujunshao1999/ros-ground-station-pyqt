cmake_minimum_required(VERSION 3.10)
project(rviz_widget LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt5 REQUIRED COMPONENTS Widgets)
find_package(rviz REQUIRED)
find_package(roscpp REQUIRED)

add_library(rviz_widget SHARED rviz_widget.cpp)

target_link_libraries(rviz_widget
    Qt5::Widgets
    ${rviz_LIBRARIES}
    ${roscpp_LIBRARIES}
)

target_include_directories(rviz_widget PRIVATE
    ${rviz_INCLUDE_DIRS}
    ${Qt5Widgets_INCLUDE_DIRS}
)

install(TARGETS rviz_widget LIBRARY DESTINATION lib)

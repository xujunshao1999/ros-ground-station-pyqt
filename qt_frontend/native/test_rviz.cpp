// Minimal test: QVBoxLayout + RViz ONLY (no button, no nesting)
#include <QApplication>
#include <QMainWindow>
#include <QVBoxLayout>
#include <QTimer>
#include <thread>
#include <chrono>
#include <ros/ros.h>
#include <cstdio>

extern "C" {
void* create_rviz_widget(void* parent_ptr);
int load_config(void* widget_ptr, const char* config_path);
void set_fixed_frame(void* widget_ptr, const char* frame);
}

int main(int argc, char** argv) {
    setbuf(stdout, NULL);
    ros::init(argc, argv, "test_rviz", ros::init_options::NoSigintHandler);
    ros::start();
    std::thread([](){while(ros::ok()){ros::spinOnce();std::this_thread::sleep_for(std::chrono::milliseconds(100));}}).detach();

    QApplication app(argc, argv);
    QMainWindow win;
    QWidget* central = new QWidget();
    QVBoxLayout* vlayout = new QVBoxLayout(central);
    vlayout->setContentsMargins(0, 0, 0, 0);
    win.setCentralWidget(central);
    win.resize(800, 600);
    win.show();

    // No button, no nesting — just RViz
    QTimer::singleShot(500, [&]() {
        printf("[C++] QVBox only RViz...\n");
        void* ptr = create_rviz_widget(nullptr);
        if (ptr) {
            QWidget* rviz = static_cast<QWidget*>(ptr);
            vlayout->addWidget(rviz, 1);
            load_config(ptr, "/home/lab118/claudeCode_Project/ros-ground-station-pyqt/qt_frontend/config/default.rviz");
            set_fixed_frame(ptr, "map");
            printf("[C++] Ready.\n");
        }
    });

    return app.exec();
}

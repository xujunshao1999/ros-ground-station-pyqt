// Test: C++ app with QHBoxLayout instead of QSplitter
#include <QApplication>
#include <QMainWindow>
#include <QHBoxLayout>
#include <QVBoxLayout>
#include <QLabel>
#include <QTimer>
#include <thread>
#include <chrono>
#include <cstdio>
#include <ros/ros.h>

extern "C" {
void* create_rviz_widget(void* parent_ptr);
int load_config(void* widget_ptr, const char* config_path);
void set_fixed_frame(void* widget_ptr, const char* frame);
}

int main(int argc, char** argv) {
    setbuf(stdout, NULL);

    ros::init(argc, argv, "qt_frontend", ros::init_options::NoSigintHandler);
    ros::start();
    std::thread([](){
        while (ros::ok()) { ros::spinOnce(); std::this_thread::sleep_for(std::chrono::milliseconds(100)); }
    }).detach();

    QApplication app(argc, argv);
    QMainWindow window;
    window.setWindowTitle("ROS Ground Station - Layout Test");
    window.resize(1600, 900);

    QWidget* central = new QWidget();
    QHBoxLayout* hbox = new QHBoxLayout(central);
    hbox->setContentsMargins(0, 0, 0, 0);

    QLabel* loading = new QLabel("Loading RViz...");
    loading->setAlignment(Qt::AlignCenter);
    hbox->addWidget(loading);

    window.setCentralWidget(central);
    window.show();

    QTimer::singleShot(200, [&]() {
        printf("[C++] Creating RViz widget...\n");
        void* container = create_rviz_widget(nullptr);
        if (!container) { loading->setText("FAILED"); return; }

        QWidget* rviz_widget = static_cast<QWidget*>(container);

        // Remove loading label, add left + rviz + right
        hbox->removeWidget(loading);
        loading->hide();

        QLabel* left = new QLabel("LEFT");
        left->setStyleSheet("background: #333; color: white; padding: 10px;");
        left->setFixedWidth(250);
        hbox->addWidget(left);

        hbox->addWidget(rviz_widget, 1);  // stretch factor 1

        QLabel* right = new QLabel("RIGHT");
        right->setStyleSheet("background: #333; color: white; padding: 10px;");
        right->setFixedWidth(350);
        hbox->addWidget(right);

        load_config(container,
            "/home/lab118/claudeCode_Project/ros-ground-station-pyqt/qt_frontend/config/default.rviz");
        set_fixed_frame(container, "map");

        printf("[C++] RViz ready in QHBoxLayout. Test mouse!\n");
    });

    return app.exec();
}

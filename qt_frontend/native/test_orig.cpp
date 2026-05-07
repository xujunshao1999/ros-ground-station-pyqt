// Original working test_rviz — QVBoxLayout + Button + RViz
#include <QApplication>
#include <QMainWindow>
#include <QVBoxLayout>
#include <QPushButton>
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
    QVBoxLayout* layout = new QVBoxLayout(central);
    win.setCentralWidget(central);

    QPushButton* btn = new QPushButton("Click me");
    layout->addWidget(btn);
    win.resize(800, 600);
    win.show();

    QTimer::singleShot(500, [&]() {
        printf("[C++] Creating RViz...\n");
        // ptr is the RenderPanel QWidget itself (original approach)
        void* ptr = create_rviz_widget(nullptr);
        if (ptr) {
            QWidget* render_panel = static_cast<QWidget*>(ptr);
            layout->addWidget(render_panel);
            // Displays created by C++ (Grid + TF), no load_config needed
            set_fixed_frame(ptr, "map");
            printf("[C++] RViz created. Test mouse!\n");
        }
    });

    return app.exec();
}

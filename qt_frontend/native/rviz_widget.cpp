#include "rviz_widget.h"

#include <QAbstractItemModel>
#include <QDockWidget>
#include <QLayout>
#include <QMainWindow>
#include <QSizePolicy>
#include <QString>
#include <QTimer>
#include <QTreeView>
#include <QVBoxLayout>
#include <QWidget>
#include <rviz/visualization_frame.h>
#include <rviz/visualization_manager.h>
#include <rviz/render_panel.h>
#include <rviz/displays_panel.h>
#include <rviz/display.h>
#include <rviz/display_group.h>
#include <rviz/panel_dock_widget.h>
#include <rviz/tool.h>
#include <rviz/tool_manager.h>
#include <rviz/yaml_config_reader.h>
#include <rviz/yaml_config_writer.h>
#include <rviz/properties/property_tree_model.h>
#include <ros/ros.h>

#include <map>

struct RvizInstance {
    rviz::VisualizationFrame* frame;
    rviz::RenderPanel* render_panel;
    rviz::VisualizationManager* manager;
    rviz::DisplaysPanel* displays_panel;
    QMainWindow* dock_host;
    bool config_dirty;
    bool dock_move_pending;
    QString config_snapshot;
};

static std::map<void*, RvizInstance*> g_instances;

static rviz::Tool* find_or_create_move_camera(rviz::ToolManager* tool_manager) {
    if (!tool_manager) return nullptr;

    for (int i = 0; i < tool_manager->numTools(); ++i) {
        rviz::Tool* tool = tool_manager->getTool(i);
        if (tool && tool->getClassId() == "rviz/MoveCamera") {
            return tool;
        }
    }

    return tool_manager->addTool("rviz/MoveCamera");
}

static void restore_interaction_state(RvizInstance* instance) {
    if (!instance || !instance->manager || !instance->render_panel) return;

    rviz::ToolManager* tool_manager = instance->manager->getToolManager();
    rviz::Tool* move_camera = find_or_create_move_camera(tool_manager);
    if (move_camera) {
        tool_manager->setDefaultTool(move_camera);
        tool_manager->setCurrentTool(move_camera);
    }

    instance->render_panel->winId();
    instance->render_panel->setMouseTracking(true);
    instance->render_panel->setFocusPolicy(Qt::StrongFocus);
    instance->render_panel->setFocus(Qt::OtherFocusReason);
}

static QString current_display_config_snapshot(RvizInstance* instance) {
    if (!instance || !instance->manager) return QString();

    rviz::Config manager_config;
    instance->manager->save(manager_config);

    rviz::Config snapshot_config;
    rviz::Config displays_config = manager_config.mapGetChild("Displays");
    if (displays_config.isValid()) {
        snapshot_config.mapMakeChild("Displays").copy(displays_config);
    }
    rviz::Config global_options_config = manager_config.mapGetChild("Global Options");
    if (global_options_config.isValid()) {
        snapshot_config.mapMakeChild("Global Options").copy(global_options_config);
    }

    rviz::YamlConfigWriter writer;
    return writer.writeString(snapshot_config, "rviz display snapshot");
}

class DockExtractor : public QObject {
    Q_OBJECT
public:
    static DockExtractor* instance() {
        static DockExtractor* s = new DockExtractor();
        return s;
    }
public Q_SLOTS:
    void onConfigChanged();
    void moveImagePanels();
};

static void mark_config_dirty(RvizInstance* inst) {
    if (inst) {
        inst->config_dirty = true;
    }
}

static void move_image_panels_to_layout(RvizInstance* inst) {
    if (!inst || !inst->dock_host) return;

    auto docks = inst->frame->findChildren<rviz::PanelDockWidget*>();
    for (auto* dw : docks) {
        QString title = dw->windowTitle();
        if (title == "Camera" || title == "Image") {
            if (!dw->parentWidget() || dw->parentWidget() != inst->dock_host) {
                dw->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
                dw->setAllowedAreas(Qt::AllDockWidgetAreas);
                dw->setFeatures(dw->features()
                                | QDockWidget::DockWidgetFloatable
                                | QDockWidget::DockWidgetMovable);
                inst->dock_host->addDockWidget(Qt::BottomDockWidgetArea, dw);
                inst->dock_host->show();
                if (inst->dock_host->parentWidget()) {
                    inst->dock_host->parentWidget()->show();
                }
            }
        }
    }
}

void DockExtractor::moveImagePanels() {
    for (auto& pair : ::g_instances) {
        RvizInstance* inst = pair.second;
        inst->dock_move_pending = false;
        move_image_panels_to_layout(inst);
    }
}

void DockExtractor::onConfigChanged() {
    bool should_schedule_move = false;
    for (auto& pair : ::g_instances) {
        RvizInstance* inst = pair.second;
        mark_config_dirty(inst);
        if (inst->dock_host && !inst->dock_move_pending) {
            inst->dock_move_pending = true;
            should_schedule_move = true;
        }
    }
    if (should_schedule_move) {
        QTimer::singleShot(0, DockExtractor::instance(), SLOT(moveImagePanels()));
    }
}

static bool g_ros_init_done = false;

void* create_rviz_widget(void* parent_ptr) {
    QWidget* parent = static_cast<QWidget*>(parent_ptr);

    if (!g_ros_init_done) {
        int argc = 1;
        static char name[] = "qt_frontend";
        static char* argv[] = {name, nullptr};
        ros::init(argc, argv, "qt_frontend", ros::init_options::NoSigintHandler);
        ros::start();
        g_ros_init_done = true;
    }

    auto* instance = new RvizInstance();
    instance->dock_host = nullptr;
    instance->config_dirty = false;
    instance->dock_move_pending = false;

    instance->frame = new rviz::VisualizationFrame();
    instance->frame->initialize();
    instance->manager = instance->frame->getManager();
    instance->render_panel = instance->manager->getRenderPanel();

    instance->render_panel->initialize(
        instance->manager->getSceneManager(), instance->manager);

    instance->render_panel->winId();  // Force native X11 window
    instance->render_panel->setMouseTracking(true);
    instance->render_panel->setFocus();

    instance->manager->setFixedFrame("map");
    instance->manager->initialize();
    instance->manager->startUpdate();
    instance->manager->removeAllDisplays();

    // Create default displays manually (avoids load_config which breaks mouse)
    instance->manager->createDisplay("rviz/Grid", "Grid", true);
    instance->manager->createDisplay("rviz/TF", "TF", true);

    restore_interaction_state(instance);
    instance->config_snapshot = current_display_config_snapshot(instance);

    instance->displays_panel = new rviz::DisplaysPanel();
    instance->displays_panel->initialize(instance->manager);
    instance->displays_panel->onInitialize();

    auto* treeView = instance->displays_panel->findChild<QTreeView*>();
    if (treeView) {
        QAbstractItemModel* model = treeView->model();
        QObject::connect(model, SIGNAL(configChanged()),
                         DockExtractor::instance(), SLOT(onConfigChanged()));
    }

    if (parent && parent->layout()) {
        parent->layout()->addWidget(instance->render_panel);
    }

    g_instances[instance->render_panel] = instance;

    return static_cast<void*>(instance->render_panel);
}

int load_config(void* widget_ptr, const char* config_path) {
    if (!widget_ptr || !config_path) return 1;

    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return 2;
    RvizInstance* instance = it->second;

    rviz::YamlConfigReader reader;
    rviz::Config config;
    reader.readFile(config, QString::fromUtf8(config_path));
    if (reader.error()) {
        ROS_ERROR_STREAM("Failed to read RViz config " << config_path << ": "
                         << reader.errorMessage().toStdString());
        return 3;
    }

    rviz::Config manager_config = config.mapGetChild("Visualization Manager");
    if (!manager_config.isValid()) {
        ROS_ERROR_STREAM("RViz config " << config_path
                         << " does not contain Visualization Manager");
        return 4;
    }

    // Load only the Visualization Manager section. Loading the full
    // VisualizationFrame also restores RViz's native window/panel/tool state,
    // which is unsafe when only RenderPanel is embedded inside PyQt.
    instance->manager->load(manager_config);
    restore_interaction_state(instance);
    instance->config_snapshot = current_display_config_snapshot(instance);
    instance->config_dirty = false;
    return 0;
}

int save_config(void* widget_ptr, const char* config_path) {
    if (!widget_ptr || !config_path) return 1;

    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return 2;
    RvizInstance* instance = it->second;

    rviz::Config config;
    rviz::Config manager_config = config.mapMakeChild("Visualization Manager");
    instance->manager->save(manager_config);

    rviz::YamlConfigWriter writer;
    writer.writeFile(config, QString::fromUtf8(config_path));
    if (writer.error()) {
        ROS_ERROR_STREAM("Failed to write RViz config " << config_path << ": "
                         << writer.errorMessage().toStdString());
        return 3;
    }

    instance->config_snapshot = current_display_config_snapshot(instance);
    instance->config_dirty = false;
    return 0;
}

int has_config_changes(void* widget_ptr) {
    if (!widget_ptr) return 0;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return 0;
    RvizInstance* instance = it->second;
    if (instance->config_dirty) return 1;
    return current_display_config_snapshot(instance) != instance->config_snapshot ? 1 : 0;
}

void set_fixed_frame(void* widget_ptr, const char* frame) {
    if (!widget_ptr || !frame) return;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return;
    it->second->manager->setFixedFrame(QString::fromUtf8(frame));
}

void* get_display_panel(void* widget_ptr) {
    if (!widget_ptr) return nullptr;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return nullptr;
    return static_cast<void*>(it->second->displays_panel);
}

void set_dock_layout(void* widget_ptr, void* layout_ptr) {
    (void)widget_ptr;
    (void)layout_ptr;
}

void set_dock_host(void* widget_ptr, void* dock_host_ptr) {
    if (!widget_ptr || !dock_host_ptr) return;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return;
    it->second->dock_host = qobject_cast<QMainWindow*>(
        static_cast<QWidget*>(dock_host_ptr));
}

long get_window_id(void* widget_ptr) {
    if (!widget_ptr) return 0;
    auto* panel = static_cast<rviz::RenderPanel*>(widget_ptr);
    return static_cast<long>(panel->winId());
}

void destroy_panel(void* widget_ptr) {
    if (!widget_ptr) return;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return;
    RvizInstance* instance = it->second;
    instance->manager->stopUpdate();
    delete instance->displays_panel;
    delete instance->frame;
    delete instance;
    g_instances.erase(it);
}

// Backward-compatible splitter wrapper
void* create_rviz_splitter(void) {
    // Create a simple container with RViz (single pane — Python can add panels)
    QWidget* container = new QWidget();
    QVBoxLayout* layout = new QVBoxLayout(container);
    layout->setContentsMargins(0, 0, 0, 0);
    void* rviz = create_rviz_widget(nullptr);
    if (rviz) {
        layout->addWidget(static_cast<QWidget*>(rviz));
    }
    return static_cast<void*>(container);
}

#include "rviz_widget.moc"

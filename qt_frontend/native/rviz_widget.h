#pragma once

#ifdef __cplusplus
extern "C" {
#endif

void* create_rviz_widget(void* parent_ptr);

void* create_rviz_splitter(void);

int load_config(void* widget_ptr, const char* config_path);

int save_config(void* widget_ptr, const char* config_path);

int has_config_changes(void* widget_ptr);

void set_fixed_frame(void* widget_ptr, const char* frame);

int can_resolve_frame(void* widget_ptr, const char* frame);

void* get_display_panel(void* widget_ptr);

void set_dock_layout(void* widget_ptr, void* layout_ptr);

void set_dock_host(void* widget_ptr, void* dock_host_ptr);

long get_window_id(void* widget_ptr);

void destroy_panel(void* widget_ptr);

#ifdef __cplusplus
}
#endif

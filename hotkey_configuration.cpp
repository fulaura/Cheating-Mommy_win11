#include <windows.h>
#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <unordered_map>
#include <filesystem>
#include <regex>
#include <conio.h>

namespace fs = std::filesystem;

// Global state for low-level hooks
static HHOOK g_kb_hook = nullptr;
static HHOOK g_mouse_hook = nullptr;
static bool g_captured = false;
static bool g_cancelled = false;
static std::string g_captured_combo = "";

// Forward declarations
static LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam);
static LRESULT CALLBACK LowLevelMouseProc(int nCode, WPARAM wParam, LPARAM lParam);

std::string get_modifier_prefix() {
    std::string prefix = "";
    bool ctrl = (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
    bool alt = (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
    bool shift = (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
    bool win = ((GetAsyncKeyState(VK_LWIN) & 0x8000) != 0) || ((GetAsyncKeyState(VK_RWIN) & 0x8000) != 0);

    if (ctrl) prefix += "ctrl+";
    if (alt) prefix += "alt+";
    if (shift) prefix += "shift+";
    if (win) prefix += "win+";
    return prefix;
}

std::string vk_to_keyname(DWORD vk) {
    // Function keys F1 - F24
    if (vk >= VK_F1 && vk <= VK_F24) {
        return "f" + std::to_string(vk - VK_F1 + 1);
    }
    // Numbers 0 - 9
    if (vk >= '0' && vk <= '9') {
        return std::string(1, (char)('0' + (vk - '0')));
    }
    // Letters A - Z
    if (vk >= 'A' && vk <= 'Z') {
        return std::string(1, (char)('a' + (vk - 'A')));
    }
    // Numpad 0 - 9
    if (vk >= VK_NUMPAD0 && vk <= VK_NUMPAD9) {
        return "num" + std::to_string(vk - VK_NUMPAD0);
    }

    switch (vk) {
        case VK_SPACE: return "space";
        case VK_TAB: return "tab";
        case VK_RETURN: return "enter";
        case VK_BACK: return "backspace";
        case VK_DELETE: return "delete";
        case VK_INSERT: return "insert";
        case VK_HOME: return "home";
        case VK_END: return "end";
        case VK_PRIOR: return "pageup";
        case VK_NEXT: return "pagedown";
        case VK_UP: return "up";
        case VK_DOWN: return "down";
        case VK_LEFT: return "left";
        case VK_RIGHT: return "right";
        case VK_CAPITAL: return "caps_lock";
        case VK_OEM_1: return ";";
        case VK_OEM_PLUS: return "=";
        case VK_OEM_COMMA: return ",";
        case VK_OEM_MINUS: return "-";
        case VK_OEM_PERIOD: return ".";
        case VK_OEM_2: return "/";
        case VK_OEM_3: return "`";
        case VK_OEM_4: return "[";
        case VK_OEM_5: return "\\";
        case VK_OEM_6: return "]";
        case VK_OEM_7: return "'";
        case VK_MULTIPLY: return "num_mul";
        case VK_ADD: return "num_add";
        case VK_SUBTRACT: return "num_sub";
        case VK_DECIMAL: return "num_dot";
        case VK_DIVIDE: return "num_div";
        default: return "";
    }
}

static LRESULT CALLBACK LowLevelKeyboardProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION && (wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN)) {
        auto* k = reinterpret_cast<KBDLLHOOKSTRUCT*>(lParam);
        DWORD vk = k->vkCode;

        // Ignore modifier keys by themselves
        if (vk == VK_LCONTROL || vk == VK_RCONTROL || vk == VK_CONTROL ||
            vk == VK_LMENU || vk == VK_RMENU || vk == VK_MENU ||
            vk == VK_LSHIFT || vk == VK_RSHIFT || vk == VK_SHIFT ||
            vk == VK_LWIN || vk == VK_RWIN) {
            return CallNextHookEx(g_kb_hook, nCode, wParam, lParam);
        }

        // Check for ESC to cancel (only when no modifiers are held)
        if (vk == VK_ESCAPE) {
            std::string prefix = get_modifier_prefix();
            if (prefix.empty()) {
                g_cancelled = true;
                g_captured = true;
                PostQuitMessage(0);
                return 1;
            }
        }

        std::string keyname = vk_to_keyname(vk);
        if (!keyname.empty()) {
            std::string prefix = get_modifier_prefix();
            g_captured_combo = prefix + keyname;
            g_captured = true;
            PostQuitMessage(0);
            return 1;
        }
    }
    return CallNextHookEx(g_kb_hook, nCode, wParam, lParam);
}

// Mouse click counting for double/triple click detection
static std::string g_last_mouse_btn = "";
static std::string g_last_mouse_mods = "";
static DWORD g_last_mouse_time = 0;
static int g_mouse_click_count = 0;
static UINT_PTR g_click_timer_id = 0;

static LRESULT CALLBACK LowLevelMouseProc(int nCode, WPARAM wParam, LPARAM lParam) {
    if (nCode == HC_ACTION) {
        auto* m = reinterpret_cast<MSLLHOOKSTRUCT*>(lParam);
        std::string mouse_btn = "";

        if (wParam == WM_LBUTTONDOWN) {
            mouse_btn = "left";
        } else if (wParam == WM_RBUTTONDOWN) {
            mouse_btn = "right";
        } else if (wParam == WM_MBUTTONDOWN) {
            mouse_btn = "middle";
        } else if (wParam == WM_XBUTTONDOWN) {
            WORD xbtn = HIWORD(m->mouseData);
            if (xbtn == XBUTTON1) mouse_btn = "x1";
            else if (xbtn == XBUTTON2) mouse_btn = "x2";
        } else if (wParam == WM_MOUSEWHEEL) {
            short delta = (short)HIWORD(m->mouseData);
            if (delta > 0) mouse_btn = "wheel_up";
            else if (delta < 0) mouse_btn = "wheel_down";
        }

        if (!mouse_btn.empty()) {
            std::string prefix = get_modifier_prefix();
            DWORD now = GetTickCount();

            // Wheel gestures resolve immediately
            if (mouse_btn == "wheel_up" || mouse_btn == "wheel_down") {
                g_captured_combo = prefix + mouse_btn;
                g_captured = true;
                PostQuitMessage(0);
                return 1;
            }

            // Check if same button and same modifiers within double-click time (400ms)
            if (mouse_btn == g_last_mouse_btn && prefix == g_last_mouse_mods && (now - g_last_mouse_time) <= 400) {
                g_mouse_click_count++;
            } else {
                g_mouse_click_count = 1;
            }

            g_last_mouse_btn = mouse_btn;
            g_last_mouse_mods = prefix;
            g_last_mouse_time = now;

            if (g_mouse_click_count >= 3) {
                // Triple click detected!
                g_captured_combo = prefix + "triple_" + mouse_btn;
                g_captured = true;
                if (g_click_timer_id) {
                    KillTimer(nullptr, g_click_timer_id);
                    g_click_timer_id = 0;
                }
                PostQuitMessage(0);
                return 1;
            } else {
                // Reset timer: wait 380ms to see if another click follows.
                // If no more clicks arrive, timer fires and accepts single or double click.
                if (g_click_timer_id) {
                    KillTimer(nullptr, g_click_timer_id);
                }
                g_click_timer_id = SetTimer(nullptr, 1, 380, [](HWND, UINT, UINT_PTR id, DWORD) {
                    KillTimer(nullptr, id);
                    g_click_timer_id = 0;
                    if (g_mouse_click_count == 2) {
                        g_captured_combo = g_last_mouse_mods + "double_" + g_last_mouse_btn;
                    } else {
                        g_captured_combo = g_last_mouse_mods + g_last_mouse_btn;
                    }
                    g_captured = true;
                    PostQuitMessage(0);
                });
                return 1;
            }
        }
    }
    return CallNextHookEx(g_mouse_hook, nCode, wParam, lParam);
}

std::string capture_hotkey_combo() {
    g_captured = false;
    g_cancelled = false;
    g_captured_combo = "";
    g_last_mouse_btn = "";
    g_last_mouse_mods = "";
    g_last_mouse_time = 0;
    g_mouse_click_count = 0;
    if (g_click_timer_id) {
        KillTimer(nullptr, g_click_timer_id);
        g_click_timer_id = 0;
    }

    // Clear message queue and wait for prior keys (like Enter) to be released
    MSG msg;
    while (PeekMessage(&msg, nullptr, 0, 0, PM_REMOVE)) {}
    while ((GetAsyncKeyState(VK_RETURN) & 0x8000) != 0) {
        Sleep(20);
    }
    Sleep(100);

    HINSTANCE hInst = GetModuleHandle(nullptr);
    g_kb_hook = SetWindowsHookExA(WH_KEYBOARD_LL, LowLevelKeyboardProc, hInst, 0);
    g_mouse_hook = SetWindowsHookExA(WH_MOUSE_LL, LowLevelMouseProc, hInst, 0);

    while (GetMessage(&msg, nullptr, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
        if (g_captured) {
            break;
        }
    }

    if (g_click_timer_id) {
        KillTimer(nullptr, g_click_timer_id);
        g_click_timer_id = 0;
    }
    if (g_kb_hook) {
        UnhookWindowsHookEx(g_kb_hook);
        g_kb_hook = nullptr;
    }
    if (g_mouse_hook) {
        UnhookWindowsHookEx(g_mouse_hook);
        g_mouse_hook = nullptr;
    }

    if (g_cancelled) {
        return "";
    }
    return g_captured_combo;
}

std::string find_config_path() {
    char exe_path[MAX_PATH]{};
    DWORD len = GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    if (len > 0) {
        fs::path exe_dir = fs::path(exe_path).parent_path();
        // 1. In same directory as exe
        if (fs::exists(exe_dir / "config.json")) {
            return (exe_dir / "config.json").string();
        }
        // 2. In parent directory (e.g. {app}\tools\ -> {app}\config.json)
        if (fs::exists(exe_dir.parent_path() / "config.json")) {
            return (exe_dir.parent_path() / "config.json").string();
        }
    }

    // 3. In Program Files install location
    const char* program_files = std::getenv("ProgramFiles(x86)");
    if (!program_files) program_files = std::getenv("ProgramFiles");
    if (program_files) {
        fs::path pf_cfg = fs::path(program_files) / "Cheating Mommy" / "config.json";
        if (fs::exists(pf_cfg)) {
            return pf_cfg.string();
        }
    }

    // 4. Current working directory
    if (fs::exists("config.json")) {
        return "config.json";
    }

    // Default fallback
    if (len > 0) {
        fs::path exe_dir = fs::path(exe_path).parent_path();
        return (exe_dir.parent_path() / "config.json").string();
    }
    return "config.json";
}

std::string read_file_content(const std::string& path) {
    std::ifstream in(path, std::ios::in | std::ios::binary);
    if (!in) return "";
    std::ostringstream ss;
    ss << in.rdbuf();
    return ss.str();
}

bool write_file_content(const std::string& path, const std::string& content) {
    std::ofstream out(path, std::ios::out | std::ios::binary | std::ios::trunc);
    if (!out) return false;
    out << content;
    return true;
}

std::string extract_hotkey(const std::string& json_text, const std::string& key_name, const std::string& default_val) {
    // Search for "key_name"\s*:\s*"([^"]*)"
    std::regex re("\"" + key_name + "\"\\s*:\\s*\"([^\"]*)\"");
    std::smatch match;
    if (std::regex_search(json_text, match, re) && match.size() > 1) {
        return match.str(1);
    }
    return default_val;
}

std::string update_hotkey_in_json(const std::string& json_text, const std::string& key_name, const std::string& new_val) {
    std::regex re("(\"" + key_name + "\"\\s*:\\s*\")[^\"]*(\")");
    if (std::regex_search(json_text, re)) {
        return std::regex_replace(json_text, re, "$1" + new_val + "$2");
    }

    // If key not found, insert inside "hotkeys": { ... }
    std::regex hotkeys_re("(\"hotkeys\"\\s*:\\s*\\{)");
    std::smatch match;
    if (std::regex_search(json_text, match, hotkeys_re)) {
        std::string replacement = "$1\n    \"" + key_name + "\": \"" + new_val + "\",";
        return std::regex_replace(json_text, hotkeys_re, replacement);
    }

    return json_text;
}

struct HotkeyEntry {
    std::string key;
    std::string label;
    std::string default_val;
};

int main() {
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    std::string config_path = find_config_path();

    std::vector<HotkeyEntry> entries = {
        {"answer_key",        "Answer & Click    (Take screenshot, AI find & click answer)", "p"},
        {"copy_key",          "Answer & Copy     (Take screenshot, AI solve & copy answer)", "o"},
        {"info_key",          "AI Info Log       (Take screenshot, AI web search & log)",   "i"},
        {"toggle_commands",   "Toggle Commands   (Enable / disable all hotkey actions)",     "l"},
        {"window_visibility", "Toggle Window     (Show / hide UI overlay window)",          "k"}
    };

    while (true) {
        std::string json_text = read_file_content(config_path);
        if (json_text.empty()) {
            std::cout << "\n[!] Warning: Could not read config file at:\n    " << config_path << "\n";
        }

        std::cout << "\n=============================================================\n";
        std::cout << "                 Cheating Mommy - Hotkey Configuration\n";
        std::cout << "=============================================================\n";

        for (size_t i = 0; i < entries.size(); ++i) {
            std::string val = extract_hotkey(json_text, entries[i].key, entries[i].default_val);
            std::cout << " " << (i + 1) << ") " << entries[i].key;
            int spaces = 20 - (int)entries[i].key.length();
            if (spaces < 1) spaces = 1;
            std::cout << std::string(spaces, ' ') << ": [" << val << "]\n";
            std::cout << "     -> " << entries[i].label << "\n";
        }

        std::cout << "\n " << (entries.size() + 1) << ") Reset all hotkeys to default (p, o, i, l, k)\n";
        std::cout << " " << (entries.size() + 2) << ") Exit\n";
        std::cout << "-------------------------------------------------------------\n";
        std::cout << "Choose an option [1-" << (entries.size() + 2) << "]: ";

        int choice = 0;
        if (!(std::cin >> choice)) {
            break;
        }

        if (choice == (int)(entries.size() + 2)) {
            break;
        }

        if (choice == (int)(entries.size() + 1)) {
            std::cout << "\nResetting hotkeys to defaults...\n";
            for (const auto& item : entries) {
                json_text = update_hotkey_in_json(json_text, item.key, item.default_val);
            }
            if (write_file_content(config_path, json_text)) {
                std::cout << ">> Successfully reset all hotkeys to defaults!\n";
            } else {
                std::cout << "[!] Failed to write to " << config_path << " (check permissions)\n";
            }
            continue;
        }

        if (choice < 1 || choice > (int)entries.size()) {
            std::cout << "Invalid choice. Please try again.\n";
            continue;
        }

        const auto& selected = entries[choice - 1];
        std::string current_val = extract_hotkey(json_text, selected.key, selected.default_val);

        std::cout << "\n=============================================================\n";
        std::cout << " Assigning Hotkey for: " << selected.key << "\n";
        std::cout << " Current assignment  : [" << current_val << "]\n";
        std::cout << "=============================================================\n";
        std::cout << ">> PRESS ANY KEY or CLICK ANY MOUSE BUTTON now...\n";
        std::cout << "   (Mouse: Left, Right, Middle, X1/Thumb-Back, X2/Thumb-Forward, Wheel)\n";
        std::cout << "   (Modifiers: Hold Ctrl, Alt, Shift, or Win while pressing/clicking)\n";
        std::cout << ">> Press [ESC] to cancel.\n\n";

        std::string captured = capture_hotkey_combo();

        if (captured.empty()) {
            std::cout << ">> Canceled. No changes made.\n";
            continue;
        }

        std::cout << ">> Detected: [" << captured << "]\n";
        json_text = update_hotkey_in_json(json_text, selected.key, captured);

        if (write_file_content(config_path, json_text)) {
            std::cout << ">> Successfully saved '" << selected.key << "' = '" << captured << "' to config.json!\n";
        } else {
            std::cout << "[!] Error writing to config file at " << config_path << "\n";
            std::cout << "    If installed in Program Files, please run this tool as Administrator.\n";
        }
    }

    return 0;
}

#include <windows.h>
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>
#include <cstdlib>
#include <filesystem>
#include <limits>

std::string appdata_path() {
    char exe_path[MAX_PATH]{};
    DWORD len = GetModuleFileNameA(nullptr, exe_path, MAX_PATH);
    if (len > 0) {
        std::filesystem::path exe_dir = std::filesystem::path(exe_path).parent_path();
        std::vector<std::filesystem::path> hint_paths = {
            exe_dir / "data_dir.txt",
            exe_dir.parent_path() / "data_dir.txt",
        };
        for (const auto& p : hint_paths) {
            std::ifstream hint(p);
            if (!hint) {
                continue;
            }
            std::string line;
            std::getline(hint, line);
            if (!line.empty()) {
                std::filesystem::create_directories(line);
                return (std::filesystem::path(line) / "credentials.txt").string();
            }
        }
    }

    const char* appdata = std::getenv("APPDATA");
    if (!appdata) return "credentials.txt";
    std::filesystem::path dir = std::filesystem::path(appdata) / "Cheating Mommy";
    std::filesystem::create_directories(dir);
    return (dir / "credentials.txt").string();
}

std::unordered_map<std::string, std::string> load_kv(const std::string& path) {
    std::unordered_map<std::string, std::string> kv;
    std::ifstream in(path);
    if (!in) return kv;

    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') continue;
        auto pos = line.find('=');
        if (pos == std::string::npos) continue;
        std::string key = line.substr(0, pos);
        std::string val = line.substr(pos + 1);
        kv[key] = val;
    }
    return kv;
}

void save_kv(const std::string& path, const std::unordered_map<std::string, std::string>& kv) {
    std::ofstream out(path, std::ios::trunc);
    const std::vector<std::string> ordered_keys = {
        "SERVER_URL",
        "LLM",
        "MODEL",
        "API",
        "ACCESS_KEY",
        "API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY"
    };

    std::unordered_map<std::string, bool> written;
    for (const auto& key : ordered_keys) {
        auto it = kv.find(key);
        if (it != kv.end()) {
            out << key << "=" << it->second << "\n";
        } else {
            out << key << "=\n";
        }
        written[key] = true;
    }

    for (const auto& pair : kv) {
        if (!written[pair.first]) {
            out << pair.first << "=" << pair.second << "\n";
        }
    }
}

std::string format_display_val(const std::string& key, const std::string& val) {
    if (val.empty()) return "(not set)";
    if (key == "SERVER_URL" || key == "LLM" || key == "MODEL") {
        return val;
    }
    if (val.length() <= 8) return "********";
    return val.substr(0, 4) + "..." + val.substr(val.length() - 4);
}

int main() {
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
    std::string path = appdata_path();
    auto kv = load_kv(path);

    const std::vector<std::string> keys = {
        "SERVER_URL",
        "LLM",
        "MODEL",
        "API",
        "ACCESS_KEY",
        "API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY"
    };

    for (const auto& k : keys) {
        if (kv.find(k) == kv.end()) {
            kv[k] = "";
        }
    }

    while (true) {
        std::cout << "\n============================================\n";
        std::cout << "          Update Credentials\n";
        std::cout << "============================================\n";
        for (size_t i = 0; i < keys.size(); ++i) {
            const auto& k = keys[i];
            std::cout << " " << (i + 1) << ") " << k;
            int spaces = 18 - static_cast<int>(k.length());
            if (spaces < 1) spaces = 1;
            std::cout << std::string(spaces, ' ') << ": [" << format_display_val(k, kv[k]) << "]\n";
        }
        std::cout << " " << (keys.size() + 1) << ") Exit\n";
        std::cout << "Choose [1-" << (keys.size() + 1) << "]: ";

        int choice = 0;
        if (!(std::cin >> choice)) return 0;
        std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');

        if (choice == static_cast<int>(keys.size() + 1)) {
            break;
        }

        if (choice < 1 || choice > static_cast<int>(keys.size())) {
            std::cout << "Invalid choice. Please try again.\n";
            continue;
        }

        std::string selected_key = keys[choice - 1];
        if (selected_key == "SERVER_URL") {
            std::cout << "\nEnter new value for SERVER_URL (enter 'local' or leave empty for local AI): ";
        } else if (selected_key == "LLM") {
            std::cout << "\nEnter LLM ('deepseek' or 'gemini'): ";
        } else if (selected_key == "MODEL") {
            std::cout << "\nEnter MODEL (e.g. 'deepseek-flash', 'gemini-2.5-flash', or empty for default): ";
        } else {
            std::cout << "\nEnter new value for " << selected_key << " (leave empty to clear): ";
        }
        std::string value;
        std::getline(std::cin, value);

        kv[selected_key] = value;
        save_kv(path, kv);
        std::cout << ">> Successfully saved " << selected_key << "!\n";
    }

    return 0;
}

#include <windows.h>
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>
#include <cstdlib>
#include <filesystem>

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
    // fixed order
    const std::vector<std::string> keys = {"SERVER_URL", "API_KEY", "ACCESS_KEY"};
    for (const auto& key : keys) {
        auto it = kv.find(key);
        if (it != kv.end()) out << key << "=" << it->second << "\n";
        else out << key << "=\n";
    }
}

int main() {
    std::string path = appdata_path();
    auto kv = load_kv(path);
    if (kv.empty()) {
        kv["SERVER_URL"] = "";
        kv["API_KEY"] = "";
        kv["ACCESS_KEY"] = "";
    }

    while (true) {
        std::cout << "\nUpdate credentials:\n";
        std::cout << "1) SERVER_URL\n";
        std::cout << "2) API_KEY\n";
        std::cout << "3) ACCESS_KEY\n";
        std::cout << "4) Exit\n";
        std::cout << "Choose: ";

        int choice = 0;
        if (!(std::cin >> choice)) return 0;
        std::cin.ignore(std::numeric_limits<std::streamsize>::max(), '\n');

        if (choice == 4) break;

        std::string key;
        if (choice == 1) key = "SERVER_URL";
        else if (choice == 2) key = "API_KEY";
        else if (choice == 3) key = "ACCESS_KEY";
        else continue;

        std::cout << "Enter new value for " << key << ": ";
        std::string value;
        std::getline(std::cin, value);

        kv[key] = value;
        save_kv(path, kv);
        std::cout << "Updated " << key << "\n";
    }

    return 0;
}

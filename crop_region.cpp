// update_crop.cpp (Windows only)
#include <windows.h>
#include <fstream>
#include <iostream>
#include <string>
#include <regex>
#include <algorithm>
#include <filesystem>

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return {};
    return std::string((std::istreambuf_iterator<char>(in)),
                       std::istreambuf_iterator<char>());
}

bool write_file(const std::string& path, const std::string& data) {
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) return false;
    out.write(data.data(), data.size());
    return true;
}

bool replace_crop_bbox(std::string& json, const std::string& new_value) {
    // Replace the value of "crop_bbox": ... (array or empty)
    std::regex re(R"("crop_bbox"\s*:\s*\[[^\]]*\])");
    if (std::regex_search(json, re)) {
        json = std::regex_replace(json, re, "\"crop_bbox\": " + new_value);
        return true;
    }
    return false;
}

int main() {
    std::filesystem::path exe_dir;
    char buffer[MAX_PATH]{};
    DWORD len = GetModuleFileNameA(nullptr, buffer, MAX_PATH);
    if (len > 0) {
        exe_dir = std::filesystem::path(buffer).parent_path();
    }
    std::string path = (exe_dir / "config.json").string();
    if (exe_dir.empty()) {
        path = "config.json";
    }

    std::cout << "Move mouse to first corner, press C.\n";
    std::cout << "Move mouse to second corner, press C.\n";
    std::cout << "Press D anytime to reset crop to [] and exit.\n";

    POINT p1{}, p2{};
    bool have_p1 = false;

    SHORT prev_c = 0, prev_d = 0;

    while (true) {
        SHORT c = GetAsyncKeyState('C');
        SHORT d = GetAsyncKeyState('D');

        if ((d & 0x8000) && !(prev_d & 0x8000)) {
            std::string json = read_file(path);
            if (json.empty()) {
                std::cout << "Failed to read " << path << "\n";
                return 1;
            }
            if (!replace_crop_bbox(json, "[]")) {
                std::cout << "crop_bbox not found in config.json\n";
                return 1;
            }
            if (!write_file(path, json)) {
                std::cout << "Failed to write " << path << "\n";
                return 1;
            }
            std::cout << "Updated crop_bbox to []\n";
            return 0;
        }

        if ((c & 0x8000) && !(prev_c & 0x8000)) {
            POINT p{};
            GetCursorPos(&p);
            if (!have_p1) {
                p1 = p;
                have_p1 = true;
                std::cout << "Corner 1: (" << p1.x << ", " << p1.y << ")\n";
                std::cout << "Move to second corner and press C...\n";
            } else {
                p2 = p;
                int left = std::min(p1.x, p2.x);
                int top = std::min(p1.y, p2.y);
                int right = std::max(p1.x, p2.x);
                int bottom = std::max(p1.y, p2.y);
                int w = std::max(0, right - left);
                int h = std::max(0, bottom - top);

                std::string new_value = "[" + std::to_string(left) + ", " +
                                        std::to_string(top) + ", " +
                                        std::to_string(w) + ", " +
                                        std::to_string(h) + "]";

                std::string json = read_file(path);
                if (json.empty()) {
                    std::cout << "Failed to read " << path << "\n";
                    return 1;
                }
                if (!replace_crop_bbox(json, new_value)) {
                    std::cout << "crop_bbox not found in config.json\n";
                    return 1;
                }
                if (!write_file(path, json)) {
                    std::cout << "Failed to write " << path << "\n";
                    return 1;
                }
                std::cout << "Updated crop_bbox to " << new_value << "\n";
                return 0;
            }
        }

        prev_c = c;
        prev_d = d;
        Sleep(30);
    }
}

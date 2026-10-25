/**
 * @file
 * @brief Norns III provenance-affinity for the VPR packer (see norns_affinity.h).
 */

#include "norns_affinity.h"

#include <algorithm>
#include <fstream>

#include "vpr_error.h"
#include "vtr_log.h"

namespace norns {

namespace {
std::string g_file;
float g_weight = 0.f;
const AtomNetlist* g_loaded_for = nullptr;
} // namespace

void set_options(const std::string& file, float weight) {
    g_file = file;
    g_weight = weight;
}

AffinityMap& global_map() {
    static AffinityMap map;
    return map;
}

void AffinityMap::load(const AtomNetlist& atom_netlist) {
    if (g_file.empty()) {
        return;
    }
    weight_ = g_weight;
    if (g_loaded_for == &atom_netlist && loaded_) {
        return;
    }
    std::ifstream in(g_file);
    if (!in) {
        VPR_FATAL_ERROR(VPR_ERROR_PACK, "Norns affinity: cannot open '%s'\n", g_file.c_str());
    }
    group_.assign(atom_netlist.blocks().size(), -1);
    members_.clear();
    size_t entries = 0;
    size_t matched = 0;
    std::string line;
    while (std::getline(in, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        // "<atom name><TAB or space><group id>"; the atom name is everything before the last separator
        size_t cut = line.find_last_of("\t ");
        if (cut == std::string::npos) {
            continue;
        }
        std::string name = line.substr(0, cut);
        int group = std::stoi(line.substr(cut + 1));
        entries++;
        AtomBlockId blk = atom_netlist.find_block(name);
        if (blk && group >= 0) {
            group_[size_t(blk)] = group;
            members_[group].push_back(blk);
            matched++;
        }
    }
    for (auto& kv : members_) { // netlist order, independent of the file's order
        std::sort(kv.second.begin(), kv.second.end());
    }
    loaded_ = true;
    g_loaded_for = &atom_netlist;
    VTR_LOG("Norns affinity: %zu of %zu file entries matched atoms, %zu groups, weight %g\n",
            matched, entries, members_.size(), (double)weight_);
}

int AffinityMap::group_of(AtomBlockId blk) const {
    if (!loaded_ || !blk) {
        return -1;
    }
    return group_[size_t(blk)];
}

const std::vector<AtomBlockId>& AffinityMap::members(int group) const {
    static const std::vector<AtomBlockId> none;
    auto it = members_.find(group);
    return it == members_.end() ? none : it->second;
}

int AffinityMap::dominant(const std::unordered_map<int, int>& counts) {
    int best = -1;
    int best_count = 0;
    for (const auto& kv : counts) {
        if (kv.second > best_count || (kv.second == best_count && kv.first < best)) {
            best = kv.first;
            best_count = kv.second;
        }
    }
    return best;
}

} // namespace norns

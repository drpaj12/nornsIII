/**
 * @file
 * @brief Norns III provenance-affinity for the VPR packer (see norns_affinity.h).
 */

#include "norns_affinity.h"

#include <algorithm>
#include <exception>
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

namespace {
std::string g_census_file;
bool g_count_queued = true;
std::ofstream g_census_stream;
unsigned long long g_cluster_seq = 0;
} // namespace

static std::string g_seed_list_file;
static std::string g_seed_dump_file;
void set_seed_options(const std::string& list_file, const std::string& dump_file) {
    g_seed_list_file = list_file;
    g_seed_dump_file = dump_file;
}
const std::string& seed_list_file() { return g_seed_list_file; }
const std::string& seed_dump_file() { return g_seed_dump_file; }
static std::string g_oracle_file;
void set_oracle_option(const std::string& file) { g_oracle_file = file; }
const std::string& oracle_file() { return g_oracle_file; }

static int g_refresh_k = 0;
static RefreshStats g_refresh_stats;
void set_refresh_options(int k) { g_refresh_k = k < 0 ? 0 : k; }
int refresh_k() { return g_refresh_k; }
RefreshStats& refresh_stats() { return g_refresh_stats; }

void set_census_options(const std::string& census_file, bool count_queued) {
    g_census_file = census_file;
    g_count_queued = count_queued;
}

bool count_queued() {
    return g_count_queued;
}

bool Census::enabled() const {
    return !g_census_file.empty();
}

std::ostream& Census::out() {
    if (!g_census_stream.is_open()) {
        g_census_stream.open(g_census_file);
        if (!g_census_stream) {
            VPR_FATAL_ERROR(VPR_ERROR_PACK, "Norns census: cannot open '%s'\n", g_census_file.c_str());
        }
    }
    return g_census_stream;
}

unsigned long long Census::new_cluster() {
    return ++g_cluster_seq;
}

void Census::flush() {
    if (g_census_stream.is_open()) {
        g_census_stream.flush();
    }
}

Census& census() {
    static Census c;
    return c;
}

ProposalStats& proposal_stats() {
    static ProposalStats stats;
    return stats;
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
    size_t line_no = 0;
    while (std::getline(in, line)) {
        line_no++;
        if (line.empty() || line[0] == '#') {
            continue;
        }
        // "<atom name><TAB or space><group id>"; the atom name is everything before the last separator
        size_t cut = line.find_last_of("\t ");
        if (cut == std::string::npos) {
            continue;
        }
        std::string name = line.substr(0, cut);
        int group = 0;
        try {
            group = std::stoi(line.substr(cut + 1));
        } catch (const std::exception&) {
            VPR_FATAL_ERROR(VPR_ERROR_PACK, "Norns affinity: '%s' line %zu: group id '%s' is not an integer (%s:%d)\n",
                            g_file.c_str(), line_no, line.substr(cut + 1).c_str(), __FILE__, __LINE__);
        }
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

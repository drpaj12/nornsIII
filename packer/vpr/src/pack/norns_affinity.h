#pragma once
/**
 * @file
 * @brief Norns III provenance-affinity for the VPR packer (overlay on VTR 3c9a4d23b2, see
 *        packer/README.md). Atoms carry an integer group id read from a file (module, word or
 *        I/O-word of the HDL construct they came from). The clusterer adds a bonus to candidates
 *        in the open cluster's dominant group and proposes members of that group as candidates.
 *        Legality is the legalizer's, unchanged. With no file, or weight 0, packing is the stock
 *        packer's.
 */

#include <ostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "atom_netlist.h"

namespace norns {

/// @brief Set the options (called once from the option setup).
void set_options(const std::string& file, float weight);

class AffinityMap {
  public:
    /// @brief Read the file for the given netlist (idempotent per netlist). No-op without a file.
    void load(const AtomNetlist& atom_netlist);

    /// @brief True when an affinity file was given and read (the group bookkeeping runs).
    bool loaded() const { return loaded_; }

    /// @brief True when the bonus and the candidate proposal are on (a file and weight > 0).
    bool active() const { return loaded_ && weight_ > 0.f; }

    float weight() const { return weight_; }

    /// @brief The group of an atom, or -1.
    int group_of(AtomBlockId blk) const;

    /// @brief The atoms of a group, in netlist order.
    const std::vector<AtomBlockId>& members(int group) const;

    /// @brief The dominant group of a count table: highest count, ties to the lower id; -1 if empty.
    static int dominant(const std::unordered_map<int, int>& counts);

  private:
    bool loaded_ = false;
    float weight_ = 0.f;
    std::vector<int> group_;                         ///< by atom block index
    std::unordered_map<int, std::vector<AtomBlockId>> members_;
};

/// @brief The packer's affinity map (loaded by the candidate selector's constructor).
AffinityMap& global_map();

/// @brief Log-only counters of the group-member proposals (no effect on packing). One call = one
///        invocation of the proposal step for a cluster; "attempted" = molecules passed to the
///        candidate queue; "queued" = molecules that actually entered the queue (the queue size grew).
struct ProposalStats {
    unsigned long long calls = 0;
    unsigned long long calls_zero_queued = 0;
    unsigned long long attempted = 0;
    unsigned long long queued = 0;
};
ProposalStats& proposal_stats();

/// @brief Census options (round 4): the log file (empty: off) and the proposal-count mode. With
///        count_queued (the default) the cap of the group-member proposal counts molecules that entered
///        the candidate queue; with "attempted" it counts the molecules handed to the queue (round 3).
void set_census_options(const std::string& census_file, bool count_queued);
bool count_queued();

/// @brief HS0 options: a seed list file (atom names, one per line; the next seed is the molecule of the first unclustered atom
///        of the list, else the stock order; empty = stock) and a log-only dump of the stock seed order (empty = off).
void set_seed_options(const std::string& list_file, const std::string& dump_file);
const std::string& seed_list_file();
const std::string& seed_dump_file();

/// @brief Q-N1b option: the known clustering C (lines "atom TAB cluster id") for the true seed oracle (empty = stock).
void set_oracle_option(const std::string& file);
const std::string& oracle_file();

/// @brief H-refresh options: k > 0 refreshes the pre-cluster criticality after every k-th closed cluster (0 = stock).
void set_refresh_options(int k);
int refresh_k();

/// @brief Log-only counters of the refresh (count and seconds spent in arc setting, timing update and seed re-sort).
struct RefreshStats {
    unsigned long long refreshes = 0;
    double seconds = 0.0;
};
RefreshStats& refresh_stats();

/// @brief Q-N3b option: weight w of the 2-hop gain term (0 = off, stock): gain = (1 - w) x stock gain + w x members_2hop / cluster atoms.
void set_twohop_weight(float w);
float twohop_weight();

/// @brief Log-only counters of the 2-hop term (evaluations and time, atom joins and time).
struct TwoHopStats {
    unsigned long long evals = 0;
    unsigned long long joins = 0;
    double eval_seconds = 0.0;
    double join_seconds = 0.0;
};
TwoHopStats& twohop_stats();

/// @brief Q-N5 options (docs/plan/q-n5-schabas-spare.md): s empty BLE slots left in up to n timing-critical logic clusters (a cluster whose seed has
///        pre-pack criticality >= crit_min closes once it holds N - s BLEs, N = BLEs per logic cluster). s = 0: stock. dump_file: log-only
///        record of every logic cluster (seed criticality, qualified, BLEs, atoms). Empty = off.
void set_spare_options(int s, int n, float crit_min, const std::string& dump_file);
int spare_bles();
int spare_clusters();
float spare_crit_min();
const std::string& spare_dump_file();

/// @brief Log-only counters of the spare-room rule.
struct SpareStats {
    unsigned long long logic_clusters = 0;
    unsigned long long qualified = 0;
    unsigned long long closed_at_limit = 0; ///< qualified clusters stopped by the limit
    unsigned long long overshoot = 0;       ///< qualified clusters that ended above N - s BLEs (a molecule spanning several BLEs)
    unsigned long long ble_total = 0;       ///< BLEs over all logic clusters
    int n_ble = 0;                          ///< BLEs per logic cluster (N)
};
SpareStats& spare_stats();

/// @brief Candidate source codes of the census (where a molecule entered the candidate queue).
enum CensusSource {
    SRC_SEED = 0,
    SRC_CONN_TIMING = 1,
    SRC_NORNS_GROUP = 2,
    SRC_TRANSITIVE = 3,
    SRC_HIGH_FANOUT = 4,
    SRC_ATTRACTION = 5,
    SRC_RAM = 6,
    SRC_UNRELATED = 7
};

/// @brief The census log (round 4): log-only, tab separated, one record per line. Off without
///        --norns_pack_census; never changes packing.
class Census {
  public:
    bool enabled() const;
    /// @brief The log stream (opened on first use; fatal error when the file cannot be opened).
    std::ostream& out();
    /// @brief A new cluster sequence number (clusters are numbered in creation order from 1).
    unsigned long long new_cluster();
    /// @brief The legalizer status of the last add_mol_to_cluster call (set by the clusterer hook).
    int last_status = 0;
    void flush();
};
Census& census();

} // namespace norns

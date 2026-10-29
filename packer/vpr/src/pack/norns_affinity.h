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

/// @brief H-refresh options: k > 0 refreshes the pre-cluster criticality after every k-th closed cluster (0 = stock).
void set_refresh_options(int k);
int refresh_k();

/// @brief Log-only counters of the refresh (count and seconds spent in arc setting, timing update and seed re-sort).
struct RefreshStats {
    unsigned long long refreshes = 0;
    double seconds = 0.0;
};
RefreshStats& refresh_stats();

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

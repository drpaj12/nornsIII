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

} // namespace norns

#pragma once
/**
 * @file
 * @brief Norns III Q-N3b: the 2-hop index behind the `members_2hop` gain term (docs/plan/q-n3b-2hop-gain.md).
 *        Header only and free of VPR types so that it can be unit tested alone (tests/test_twohop.py).
 *
 * For an open cluster Cl and a candidate molecule M, members_2hop(M) = the number of atoms of Cl that are within two hops of an
 * atom of M (one hop = two atoms share a net; the caller's neighbour function decides which nets count). The index is
 * incremental: add(atom, nbrs) runs a 2-hop breadth-first search from an atom that joins the cluster and records, for every
 * atom reached, the join index of that cluster atom. count(M) is then the size of the union of those records over M's atoms.
 */

#include <cstddef>
#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace norns {

class TwoHopIndex {
  public:
    /// @brief An atom joins the cluster. nbrs(a, out) must append the 1-hop neighbours of atom a (it may contain duplicates and a itself).
    template<class NbrFn>
    void add(uint32_t atom, NbrFn nbrs) {
        const uint32_t idx = n_++;
        std::unordered_set<uint32_t> seen{atom};
        std::vector<uint32_t> h1, tmp;
        nbrs(atom, h1);
        std::vector<uint32_t> first;
        for (uint32_t b : h1) {
            if (seen.insert(b).second) first.push_back(b);
        }
        std::vector<uint32_t> reached = first;
        for (uint32_t b : first) {
            tmp.clear();
            nbrs(b, tmp);
            for (uint32_t c : tmp) {
                if (seen.insert(c).second) reached.push_back(c);
            }
        }
        for (uint32_t r : reached) reach_[r].push_back(idx);
    }

    /// @brief Atoms of the cluster within two hops of at least one of the given atoms.
    unsigned count(const uint32_t* atoms, size_t n) const {
        if (n == 1) {
            auto it = reach_.find(atoms[0]);
            return it == reach_.end() ? 0u : (unsigned)it->second.size();
        }
        std::unordered_set<uint32_t> u;
        for (size_t i = 0; i < n; i++) {
            auto it = reach_.find(atoms[i]);
            if (it != reach_.end()) u.insert(it->second.begin(), it->second.end());
        }
        return (unsigned)u.size();
    }

    /// @brief Atoms that have joined the cluster.
    unsigned size() const { return n_; }

  private:
    unsigned n_ = 0;
    std::unordered_map<uint32_t, std::vector<uint32_t>> reach_;
};

} // namespace norns

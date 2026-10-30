// Unit test of norns::TwoHopIndex (Q-N3b). Chain a-b-c-d-e (4 two-pin nets), f isolated, g-h on a net with 40 sinks is not built here
// (the net cap belongs to the neighbour function of the selector). Cluster = {a, b}.
#include <cstdio>
#include <map>
#include <vector>
#include "../vpr/src/pack/norns_twohop.h"

enum { A, B, C, D, E, F };
static int fails = 0;
#define CHECK(x, want) do { unsigned got = (x); if (got != (unsigned)(want)) { std::printf("FAIL line %d: %s = %u, want %u\n", __LINE__, #x, got, (unsigned)(want)); fails++; } } while (0)

int main() {
    std::map<uint32_t, std::vector<uint32_t>> adj = {{A, {B}}, {B, {A, C}}, {C, {B, D}}, {D, {C, E}}, {E, {D}}, {F, {}}};
    auto nbrs = [&](uint32_t a, std::vector<uint32_t>& out) { for (uint32_t x : adj[a]) out.push_back(x); };
    norns::TwoHopIndex idx;
    CHECK(idx.size(), 0);
    idx.add(A, nbrs);
    idx.add(B, nbrs);
    CHECK(idx.size(), 2);
    uint32_t c[] = {C}, d[] = {D}, e[] = {E}, f[] = {F}, de[] = {D, E}, cd[] = {C, D};
    CHECK(idx.count(c, 1), 2);   // c: a (2 hops), b (1 hop)
    CHECK(idx.count(d, 1), 1);   // d: b (2 hops)
    CHECK(idx.count(e, 1), 0);
    CHECK(idx.count(f, 1), 0);
    CHECK(idx.count(de, 2), 1);  // union over the molecule: {b}
    CHECK(idx.count(cd, 2), 2);  // union {a, b}, not 3
    // duplicates in the neighbour list do not change the counts
    auto dup = [&](uint32_t a, std::vector<uint32_t>& out) { for (uint32_t x : adj[a]) { out.push_back(x); out.push_back(x); } out.push_back(a); };
    norns::TwoHopIndex idx2;
    idx2.add(A, dup);
    idx2.add(B, dup);
    CHECK(idx2.count(c, 1), 2);
    CHECK(idx2.count(d, 1), 1);
    std::printf(fails ? "FAILED\n" : "OK\n");
    return fails ? 1 : 0;
}

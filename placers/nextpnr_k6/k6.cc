/*
 *  Norns III: a nextpnr "viaduct" micro-architecture for the VTR k6_frac_N10 grid (placement only).
 *
 *  Derived from the structure of generic/viaduct/example/example.cc in nextpnr
 *  (Copyright (C) 2021 gatecat <gatecat@ds0.me>, ISC licence); this file is new code written for
 *  the Norns III experiment and is distributed under the same ISC licence:
 *
 *  Permission to use, copy, modify, and/or distribute this software for any
 *  purpose with or without fee is hereby granted, provided that the above
 *  copyright notice and this permission notice appear in all copies.
 *
 *  THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
 *  WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
 *  ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 *  WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 *  ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 *  OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 *
 *  What it models (VTR arch k6_frac_N10_frac_chain_mem32K_40nm.xml, auto layout):
 *   - grid W x H including the IO ring (VPR "FPGA sized to W x H"), x in [0,W), y in [0,H);
 *   - IO ring: perimeter tiles except the four corners, 8 IOB bels per tile (z = sub tile);
 *   - CLB tiles: every interior column except x % 8 == 2 (memory columns) and x % 8 == 6
 *     (mult_36 columns); 10 BLE bels per tile (z = k). pack() merges a LUT6 whose only sink is a DFF D pin
 *     with that DFF into one BLE cell (VPR's lut -> ff molecule); a lone LUT6 or a lone DFF is a BLE too;
 *   - tile validity: at most 40 distinct nets entering the tile (the 40 "I" pins; own outputs
 *     feed back for free), as in the arch XML.
 *  Not modelled: LUT fracturing (two LUT5 per LUT6), carry chains, mult_36 and memory (their
 *  columns hold no bels: cells of those types are rejected by the converter), clocks (clock nets
 *  are removed by the converter, like VPR's placer ignores them), routing (dummy wires only, run
 *  with --no-route), cell timing (none in the generic arch).
 */

#include <cstdlib>

#include "log.h"
#include "nextpnr.h"
#include "util.h"
#include "viaduct_api.h"
#include "viaduct_helpers.h"

#define GEN_INIT_CONSTIDS
#define VIADUCT_CONSTIDS "viaduct/k6/constids.inc"
#include "viaduct_constids.h"

NEXTPNR_NAMESPACE_BEGIN

namespace {
struct K6Impl : ViaductAPI
{
    explicit K6Impl(const dict<std::string, std::string> &args)
    {
        auto get = [&](const char *k, int dflt) {
            auto it = args.find(k);
            return it == args.end() ? dflt : std::atoi(it->second.c_str());
        };
        W = get("width", 12);
        H = get("height", 12);
        N = get("n", 10);
        Imax = get("inputs", 40);
        if (W < 3 || H < 3)
            log_error("k6 uarch: width and height must be at least 3 (got %d x %d)\n", W, H);
    }
    ~K6Impl() {};

    void init(Context *ctx) override
    {
        init_uarch_constids(ctx);
        ViaductAPI::init(ctx);
        h.init(ctx);
        log_info("k6 uarch: grid %d x %d, %d BLEs per CLB, %d CLB inputs\n", W, H, N, Imax);
        init_bels();
    }

    void pack() override
    {
        // Merge a LUT6 whose only sink is a DFF D pin with that DFF into one BLE cell (VPR's lut -> ff molecule, which
        // VPR's AP flow requires to sit at one location). The BLE cell keeps the LUT's name and records the DFF's
        // name in the string attribute FF_ATOM; a lone LUT6 or DFF is retyped to BLE. A relative-constraint chain
        // is not used: nextpnr's SA legaliser (common/place/place_common.cc, valid_loc_for) refuses a tile that
        // already holds a locked chain, so SA could not start on a design with more chains than tiles.
        std::vector<IdString> trim_cells, trim_nets;
        int merged = 0;
        for (auto &cell : ctx->cells) {
            CellInfo *ff = cell.second.get();
            if (ff->type != id_DFF)
                continue;
            NetInfo *d = ff->getPort(id_D);
            if (!d || !d->driver.cell || d->driver.cell->type != id_LUT6 || d->driver.port != id_F ||
                d->users.entries() != 1)
                continue;
            CellInfo *lut = d->driver.cell;
            ff->movePortTo(id_Q, lut, id_Q);
            lut->attrs[ctx->id("FF_ATOM")] = ff->name.str(ctx);
            lut->disconnectPort(id_F);
            ff->disconnectPort(id_D);
            trim_cells.push_back(ff->name);
            trim_nets.push_back(d->name);
            ++merged;
        }
        for (auto c : trim_cells)
            ctx->cells.erase(c);
        for (auto n : trim_nets)
            ctx->nets.erase(n);
        for (auto &cell : ctx->cells)
            if (cell.second->type == id_LUT6 || cell.second->type == id_DFF)
                cell.second->type = id_BLE;
        log_info("Merged %d LUT6-DFF pairs into BLE cells.\n", merged);
    }

    void prePlace() override { assign_cell_info(); }

    bool isBelLocationValid(BelId bel, bool explain_invalid) const override
    {
        Loc l = ctx->getBelLocation(bel);
        if (is_io(l.x, l.y))
            return true;
        return tile_valid(l.x, l.y, explain_invalid);
    }

    IdString getBelBucketForCellType(IdString cell_type) const override { return cell_type; }
    bool isValidBelForCellType(IdString cell_type, BelId bel) const override
    {
        return ctx->getBelType(bel) == cell_type;
    }

  private:
    ViaductHelpers h;
    int W = 12, H = 12, N = 10, Imax = 40;
    std::vector<std::vector<BelId>> tile_ble; // [y * W + x][k]

    bool is_io(int x, int y) const { return x == 0 || x == W - 1 || y == 0 || y == H - 1; }
    bool is_corner(int x, int y) const { return (x == 0 || x == W - 1) && (y == 0 || y == H - 1); }
    bool is_clb_col(int x) const { return (x % 8) != 2 && (x % 8) != 6; }

    WireId dummy_wire(int x, int y, const std::string &name)
    {
        return ctx->addWire(h.xy_id(x, y, ctx->id(name)), ctx->id("W"), x, y);
    }

    void init_bels()
    {
        tile_ble.resize(W * H);
        int nclb = 0, nio = 0;
        for (int y = 0; y < H; y++) {
            for (int x = 0; x < W; x++) {
                if (is_corner(x, y))
                    continue;
                if (is_io(x, y)) {
                    for (int z = 0; z < 8; z++) {
                        BelId b = ctx->addBel(h.xy_id(x, y, ctx->idf("IO%d", z)), id_IOB, Loc(x, y, z), false, false);
                        ctx->addBelInput(b, id_I, dummy_wire(x, y, stringf("IO%d_I", z)));
                        ctx->addBelOutput(b, id_O, dummy_wire(x, y, stringf("IO%d_O", z)));
                        ++nio;
                    }
                } else if (is_clb_col(x)) {
                    for (int k = 0; k < N; k++) {
                        BelId ble = ctx->addBel(h.xy_id(x, y, ctx->idf("BLE%d", k)), id_BLE, Loc(x, y, k), false, false);
                        for (int i = 0; i < 6; i++)
                            ctx->addBelInput(ble, ctx->idf("I%d", i), dummy_wire(x, y, stringf("B%d_L%d", k, i)));
                        ctx->addBelInput(ble, id_D, dummy_wire(x, y, stringf("B%d_D", k)));
                        ctx->addBelInput(ble, id_CLK, dummy_wire(x, y, stringf("B%d_CLK", k)));
                        ctx->addBelOutput(ble, id_F, dummy_wire(x, y, stringf("B%d_F", k)));
                        ctx->addBelOutput(ble, id_Q, dummy_wire(x, y, stringf("B%d_Q", k)));
                        tile_ble[y * W + x].push_back(ble);
                    }
                    ++nclb;
                }
            }
        }
        log_info("k6 uarch: %d CLB tiles, %d IOB bels\n", nclb, nio);
    }

    struct K6CellInfo
    {
        std::vector<const NetInfo *> in;  // input nets (I0..I5, D)
        std::vector<const NetInfo *> out; // output nets (F, Q)
    };
    std::vector<K6CellInfo> fast_cell_info;
    void assign_cell_info()
    {
        fast_cell_info.clear();
        fast_cell_info.resize(ctx->cells.size());
        for (auto &cell : ctx->cells) {
            CellInfo *ci = cell.second.get();
            if (ci->type != id_BLE)
                continue;
            auto &fc = fast_cell_info.at(ci->flat_index);
            for (int i = 0; i < 6; i++)
                if (const NetInfo *n = ci->getPort(ctx->idf("I%d", i)))
                    fc.in.push_back(n);
            if (const NetInfo *n = ci->getPort(id_D))
                fc.in.push_back(n);
            if (const NetInfo *n = ci->getPort(id_F))
                fc.out.push_back(n);
            if (const NetInfo *n = ci->getPort(id_Q))
                fc.out.push_back(n);
        }
    }

    // A tile is legal when the number of distinct nets that enter it from outside is at most Imax.
    bool tile_valid(int x, int y, bool explain) const
    {
        std::vector<const NetInfo *> driven, ins;
        for (const BelId b : tile_ble[y * W + x]) {
            const CellInfo *ci = ctx->getBoundBelCell(b);
            if (!ci)
                continue;
            const auto &fc = fast_cell_info.at(ci->flat_index);
            for (const NetInfo *n : fc.out)
                driven.push_back(n);
            for (const NetInfo *n : fc.in)
                ins.push_back(n);
        }
        std::sort(ins.begin(), ins.end());
        ins.erase(std::unique(ins.begin(), ins.end()), ins.end());
        int ext = 0;
        for (const NetInfo *n : ins)
            if (std::find(driven.begin(), driven.end(), n) == driven.end())
                ++ext;
        if (ext > Imax) {
            if (explain)
                log_info("k6 tile (%d,%d): %d external input nets exceed %d\n", x, y, ext, Imax);
            return false;
        }
        return true;
    }
};

struct K6Arch : ViaductArch
{
    K6Arch() : ViaductArch("k6") {};
    std::unique_ptr<ViaductAPI> create(const dict<std::string, std::string> &args)
    {
        return std::make_unique<K6Impl>(args);
    }
} k6Arch;
} // namespace

NEXTPNR_NAMESPACE_END

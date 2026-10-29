# Terms for the Norns III paper (Background and Methodology order)

Ordered so that every term depends only on terms above it. `defined at` is the line of the source where the paper first defines the term: the glossary (docs/paper/n-background.tex, one definition per line, in this order) or, for the five terms the Introduction has to use first (FPGA, HDL, placement, packing, leak and the yardstick), the plain-English definition in n-intro.tex; the glossary restates those. `first used at` is where the term first occurs outside the abstract; `search` is the regular expression the checker uses. Check with `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex` (the abstract is exempt). The words area, speed and power are used as plain words and are explained in Methodology (Section Metrics), not checked. Regenerated 2026-10-28 for the step-2 rewrite.
| term | definition | defined at | first used at | depends on | search |
|---|---|---|---|---|---|
| FPGA | A chip made of many small programmable logic blocks joined by programmable wires; a design is loaded onto it. | n-intro.tex:4 | n-intro.tex:4 | - | `\bFPGAs?\b` |
| netlist | A list of the logic gates of a design and the wires between them. | n-background.tex:12 | n-background.tex:12 | - | `\bnetlists?\b` |
| HDL | Hardware description language: the Verilog text a designer writes. | n-intro.tex:4 | n-intro.tex:4 | - | `\bHDL\b` |
| LUT | Look-up table: the small memory that implements any logic function of a few inputs. | n-background.tex:14 | n-background.tex:14 | - | `\bLUTs?\b` |
| K | The number of inputs of a LUT; here K = 6. | n-background.tex:15 | n-background.tex:15 | LUT | `six-input\|\bK~?=\|\$K=\|\$K\$` |
| BLE | Basic logic element: one LUT with its flip-flop. | n-background.tex:16 | n-background.tex:16 | LUT | `\bBLEs?\b` |
| cluster / clustering | A set of netlist blocks meant to belong together; a clustering is a partition of the netlist into clusters. | n-background.tex:17 | n-background.tex:17 | netlist | `\bclusters?\b\|clustering\|partition` |
| cut | The number of nets whose pins lie in more than one cluster of a clustering. | n-background.tex:18 | n-background.tex:18 | cluster / clustering; netlist | `\bcuts?\b(?! across\| into)` |
| Rent exponent | The p of Rent's rule T = k B^p fitted to terminals of blocks found by recursive bisection; real logic about 0.5 to 0.7. | n-background.tex:19 | n-background.tex:19 | netlist; cluster / clustering | `Rent` |
| CLB | Configurable logic block: a group of 10 BLEs placed as one unit. | n-background.tex:20 | n-background.tex:20 | BLE | `\bCLBs?\b` |
| module | One HDL module, the unit of the design hierarchy. | n-background.tex:21 | n-background.tex:21 | HDL | `\bmodules?\b` |
| provenance | The record kept on every netlist object of which HDL text, and which module, it came from. | n-background.tex:22 | n-background.tex:22 | HDL; netlist; module | `provenance` |
| word | A group of netlist blocks that are the bits of one HDL vector (a register, an adder or a bus). | n-background.tex:23 | n-background.tex:23 | HDL; netlist | `\bwords?\b` |
| io-word | A word made from a top-level input or output bus, extended inward to the logic next to it. | n-background.tex:24 | n-background.tex:24 | word | `io-words?` |
| placement | The choice of which site on the chip each block occupies. | n-intro.tex:4 | n-intro.tex:4 | - | `\bplace(ment\|d)\b\|\bplacers?\b` |
| routing | The choice of which wire segments connect the placed blocks. | n-background.tex:26 | n-background.tex:26 | placement | `\brout(ed\|ing\|er)\b` |
| VPR | The place-and-route program of the VTR flow. | n-background.tex:27 | n-background.tex:27 | placement; routing | `\bVPR\b` |
| wirelength | Total length of the routed wires of a design (WL). | n-background.tex:28 | n-background.tex:28 | routing | `wirelength\|\bWL\b` |
| critical path | The slowest register-to-register path of a design; it sets the clock speed. | n-background.tex:29 | n-background.tex:29 | netlist | `critical.path` |
| CPD | Critical-path delay: the delay of the critical path, in ns. | n-background.tex:30 | n-background.tex:30 | critical path | `\bCPD\b\|critical-path delay` |
| slack | How much earlier than required a signal arrives; negative means the clock is too fast. | n-background.tex:31 | n-background.tex:31 | CPD; VPR | `\bslack\b` |
| criticality | A connection's closeness to the CPD, 1 - slack/CPD; an atom's criticality is the largest over the paths or pins that contain it. | n-background.tex:32 | n-background.tex:32 | CPD; slack | `\bcriticalit(y\|ies)\b` |
| near-critical | A path or connection whose delay is within a stated fraction of the CPD. | n-background.tex:33 | n-background.tex:33 | critical path; CPD; slack; VPR | `near-critical` |
| channel width | Number of routing tracks per channel. | n-background.tex:34 | n-background.tex:34 | routing | `channel.width\|chan\.` |
| packing | The step that groups LUTs and flip-flops into CLBs before placement. | n-intro.tex:4 | n-intro.tex:4 | - | `\bpack(ing\|er\|ed\|ings)?\b\|AAPack` |
| simulated annealing | A placement search that accepts worse moves at a falling temperature. | n-background.tex:36 | n-background.tex:36 | placement | `simulated.annealing\|\banneal` |
| analytic placement | A placement computed by solving a smooth wirelength model; VPR's start for the anneal. | n-background.tex:37 | n-background.tex:37 | placement; wirelength; VPR; simulated annealing | `\banalytic` |
| affinity packing (Norns packer) | A copy of VPR's packer with a bonus beta for adding atoms of the same word or module to a CLB. | n-background.tex:38 | n-background.tex:38 | packing; word; module; VPR; CLB | `affinity\|\\beta\|Norns packer` |
| purity | The share of a CLB's labelled atoms that carry its most common word (or module). | n-background.tex:39 | n-background.tex:39 | CLB; word | `\bpurity\b` |
| split factor | How many CLBs a word spans divided by the fewest it could span. | n-background.tex:40 | n-background.tex:40 | word; CLB | `split factor` |
| known-optimum yardstick | Designs built from blocks that each fill one CLB, so the intended clustering is known by construction. | n-intro.tex:15 | n-intro.tex:15 | - | `yardstick\|by construction\|known grouping\|known clustering\|known arm\|\\emph\{known\}` |
| foreign clustering | A clustering that VPR did not make (METIS), used so VPR is not graded on its own answer. | n-background.tex:42 | n-background.tex:42 | cluster / clustering; known-optimum yardstick | `foreign` |
| alignment | How closely the HDL words match the yardstick's blocks: 1 is the leak, 0 means words span about ten blocks. | n-background.tex:43 | n-background.tex:43 | word; known-optimum yardstick | `alignment` |
| leak | A gain that exists only because the input file already equals the answer. | n-intro.tex:16 | n-intro.tex:16 | - | `\bleak` |
| pairing class | Class of a pair of atoms in one CLB: series-critical, series-noncritical, shared-input, orthogonal, filler. | n-background.tex:45 | n-background.tex:45 | CLB | `pairing class\|series-critical\|series-noncritical\|shared-input` |
| critical heap | The set of atoms of criticality at least 0.90, which the greedy packer takes first. | n-background.tex:46 | n-background.tex:46 | near-critical; criticality; packing | `critical heap` |
| pack-time heap | The critical heap as the packer sees it: pack-time criticality at least 0.90. | n-background.tex:47 | n-background.tex:47 | critical heap; packing | `pack-time heap` |
| post-route heap | The critical heap of the routed design: criticality at least 0.90 in the 1000-path report. | n-background.tex:48 | n-background.tex:48 | critical heap; routing | `post-route heap` |
| stale pick | A pick made on pack-time criticality at least 0.90 that holds no post-route heap atom. | n-background.tex:49 | n-background.tex:49 | pack-time heap; post-route heap | `stale picks?` |
| exception HDL pattern | A detectable HDL construct for which grouping by HDL structure is a bad packing hint or the greedy pick goes wrong. | n-background.tex:50 | n-background.tex:50 | HDL; word; packing | `exception HDL pattern` |
| seed (initial placement) | A placement file given to VPR to start the anneal from; soft or hard. | n-background.tex:51 | n-background.tex:51 | simulated annealing; VPR; placement | `\bseeds?\b\|seeded\|\bsoft (seed\|arm)\|\bhard (arm\|seed\|region)` |
| Urd | The provenance seed: its clusters are the HDL modules. | n-background.tex:52 | n-background.tex:52 | seed (initial placement); provenance; module; cluster / clustering | `\bUrd\b` |
| Verdandi | Recovered seed: clusters found from the flat netlist alone. | n-background.tex:53 | n-background.tex:53 | seed (initial placement); cluster / clustering; netlist | `\bVerdandi\b\|Louvain` |
| quotient layout | Contract each cluster to a node, weight edges by cut nets, lay the small graph out, scale to the die. | n-background.tex:54 | n-background.tex:54 | cluster / clustering | `quotient` |
| scale S | The anneal's start temperature as a multiple of VPR's automatic estimate. | n-background.tex:55 | n-background.tex:55 | simulated annealing; VPR | `temperature scale\|scale~?1\|\$S\$\|scale \$S\$` |
| crossover | The largest tested scale S at which a seeded cold start still routes shorter than an unseeded run. | n-background.tex:56 | n-background.tex:56 | scale S; seed (initial placement) | `crossover` |
| retention | Fraction of a seed's CLBs still inside the seed cluster's region at exit. | n-background.tex:57 | n-background.tex:57 | seed (initial placement); CLB; cluster / clustering | `retention` |
| hindsight clustering | Stock clustering with atoms moved or swapped between neighbouring CLBs according to where the best stock placement put them. | n-background.tex:58 | n-background.tex:58 | packing; placement; CLB | `hindsight` |
| flat-placement file | VPR's one-line-per-atom placement file through which an outside placer enters VPR. | n-background.tex:59 | n-background.tex:59 | placement; VPR | `flat.place` |
| nextpnr | An open-source FPGA placer with an analytic mode (HeAP) and an annealing mode (SA). | n-background.tex:60 | n-background.tex:60 | placement | `nextpnr\|(?-i:HeAP)` |
| reread control | The control that reads VPR's own final placement back into the default flow. | n-background.tex:61 | n-background.tex:61 | flat-placement file; VPR | `reread` |
| rule H0 | Adders, multipliers, RAMs and pads are fixed at VPR's analytic positions for the external placers. | n-background.tex:62 | n-background.tex:62 | nextpnr; analytic placement | `Rule H0\|rule H0` |
| run record | A mimir-run.json per VPR or nextpnr run: commands, tool commits, parameters with their source, hashes. | n-background.tex:63 | n-background.tex:63 | VPR; nextpnr | `run records?\|mimir-run` |
| geomean ratio | Geometric mean over designs of variant over reference. | n-background.tex:64 | n-background.tex:64 | - | `geomean\|geometric mean` |
| sign test | Exact two-sided test on how many designs improve. | n-background.tex:65 | n-background.tex:65 | geomean ratio | `sign test` |
| Wilcoxon test | Rank test of paired per-design differences. | n-background.tex:66 | n-background.tex:66 | geomean ratio | `Wilcoxon` |
| Holm adjustment | Correction of p-values for several simultaneous tests. | n-background.tex:67 | n-background.tex:67 | Wilcoxon test | `\bHolm\b` |
| bootstrap interval | Confidence interval from resampling the designs. | n-background.tex:68 | n-background.tex:68 | geomean ratio | `bootstrap` |
| verdict rule | The numeric rule that maps a result to supported, not supported or inconclusive. | n-background.tex:69 | n-background.tex:69 | geomean ratio | `verdict rule` |

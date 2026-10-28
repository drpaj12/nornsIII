# Terms for the Norns III paper (Background and Methodology order)

Ordered so that every term depends only on terms above it. `defined at` is the flattened-paper
position where the paper explains the term now (`none`: the paper never defines it); `first used at`
is where the term first occurs outside the abstract; `search` is the regular expression the checker
uses. Check with `python3 docs/paper/check_terms.py --tex docs/paper/norns.tex` (the abstract is exempt).
Generated 2026-10-28 against origin/main be9096c; line numbers are the .tex files' own lines.
| term | definition | defined at | first used at | depends on | search |
|---|---|---|---|---|---|
| FPGA | A chip made of many small programmable logic blocks and wires that a design is loaded onto. | none | norns.tex:75 | - | `\bFPGAs?\b` |
| netlist | A list of the logic gates (or LUTs) of a design and the wires between them. | none | norns.tex:87 | - | `\bnetlists?\b` |
| HDL | Hardware description language: the Verilog text a designer writes. | none | norns.tex:112 | - | `\bHDL\b` |
| LUT | Look-up table: the small memory that implements any logic function of K inputs. | none | norns.tex:179 | - | `\bLUTs?\b` |
| K | The number of inputs of a LUT; here K = 6. | norns.tex:178 | norns.tex:178 | LUT | `six-input\|\bK~?=` |
| BLE | Basic logic element: one LUT with its flip-flop. | r8-results.tex:23 | r8-results.tex:23 | LUT | `\bBLEs?\b\|basic element` |
| CLB | Configurable logic block: a group of 10 BLEs that is placed as one unit. | none | norns.tex:195 | BLE | `\bCLBs?\b` |
| provenance | The record, on every netlist object, of which HDL text and which module it came from. | norns.tex:146 | norns.tex:29 | HDL; netlist | `provenance` |
| elaboration | The front-end step that turns HDL text into a design graph before any gates exist. | none | r4-results.tex:141 | HDL | `elaborat` |
| IR | Intermediate representation: Odin III's one internal design graph. | none | norns.tex:118 | netlist | `\bIR\b` |
| module | One HDL module; the unit of the design hierarchy. | norns.tex:146 | norns.tex:146 | HDL; provenance | `\bmodules?\b` |
| placement | The choice of which site on the chip each block occupies. | none | norns.tex:29 | CLB | `\bplace(ment\|d)\b\|\bplacers?\b` |
| routing | The choice of which wires connect the placed blocks. | none | norns.tex:301 | placement | `\brout(ed\|ing\|er)\b` |
| wirelength | Total length of the routed wires of a design; lower is smaller and usually faster. | none | norns.tex:302 | routing | `wirelength` |
| critical path | The slowest register-to-register path; it sets the clock speed. | none | norns.tex:137 | netlist | `critical.path` |
| CPD | Critical-path delay: the delay of the critical path, in ns. | none | norns.tex:302 | critical path | `\bCPD\b\|critical-path delay` |
| slack | How much earlier than required a signal arrives; negative means the clock is too fast. | none | r5-method.tex:5 | CPD | `\bslack\b` |
| near-critical | A path whose delay is within a stated percentage of the critical path. | r4-results.tex:6 | r4-method.tex:29 | critical path | `near-critical` |
| channel width | Number of routing tracks per channel; the smaller the routable width, the less wire area. | none | norns.tex:302 | routing | `channel width` |
| VPR | The place-and-route program of the VTR flow. | none | norns.tex:82 | placement; routing | `\bVPR\b` |
| packing | The step that groups LUTs and flip-flops into CLBs before placement (VPR's AAPack). | r3-method.tex:10 | norns.tex:111 | CLB; LUT | `\bpack(ing\|er\|ed\|ings)?\b` |
| simulated annealing | A placement search that accepts worse moves at a falling temperature to escape bad layouts. | norns.tex:132 | norns.tex:29 | placement | `simulated.annealing\|\banneal` |
| analytic placement | A placement computed by solving a smooth wirelength model; VPR's start for the anneal. | norns.tex:132 | norns.tex:94 | placement | `analytic` |
| seed (initial placement) | A placement file given to VPR to start the anneal from, instead of its own start. | norns.tex:167 | norns.tex:95 | simulated annealing; placement | `\bseeds?\b\|seeded` |
| checkpointing | VPR's save-best-and-restore flag in the anneal (from RLPlace). | norns.tex:137 | norns.tex:93 | simulated annealing | `checkpoint` |
| cluster / clustering | A partition of the netlist blocks into groups that are meant to belong together. | norns.tex:167 | norns.tex:30 | netlist | `\bclusters?\b\|clustering\|partition` |
| Urd (provenance seed) | The seed whose clusters are the HDL modules. | norns.tex:146 | norns.tex:146 | provenance; module; cluster / clustering | `\bUrd\b` |
| Verdandi (recovered clusters) | Clusters recovered from the flat netlist alone (Loki III L2: Louvain, spectral, affinity propagation, k-means). | norns.tex:153 | norns.tex:118 | cluster / clustering | `Verdandi\|Louvain` |
| quotient layout | Contract each cluster to a node, weight edges by cut nets, lay the small graph out, scale to the die. | norns.tex:168 | norns.tex:100 | cluster / clustering | `quotient` |
| soft / hard seed | Soft: an initial placement the anneal may leave. Hard: floorplan regions the anneal must respect. | norns.tex:206 | norns.tex:187 | seed (initial placement) | `\bsoft\b\|\bhard arm\|hard seed\|hard region` |
| scale S (start temperature) | The anneal's start temperature as a multiple of VPR's own automatic estimate. | norns.tex:291 | norns.tex:96 | simulated annealing | `temperature scale\|scale~?1\|\$S\$` |
| crossover | The largest tested scale at which a seeded cold start still routes shorter than an unseeded run. | norns.tex:287 | norns.tex:103 | scale S (start temperature) | `crossover` |
| retention | Fraction of a seed's CLBs still inside the seed cluster's region at exit. | norns.tex:247 | norns.tex:105 | seed (initial placement) | `retention` |
| word | A group of netlist blocks that are the bits of one HDL vector (a register, adder, bus). | r2-method.tex:10 | norns.tex:107 | HDL; netlist | `\bwords?\b` |
| bit-slice | One bit position across the words of a datapath; slices are laid out as aligned rows. | r2-method.tex:40 | norns.tex:107 | word | `bit.slic\|slices` |
| io-word | A top-level input or output bus, extended inward to nearby logic. | r3-method.tex:40 | r3-method.tex:40 | word | `io-words?` |
| purity | Plurality share: the share of a CLB's labelled atoms that carry its most common word (or module). | r3-method.tex:34 | r3-method.tex:18 | CLB; word | `\bpurity\b` |
| split factor | How many CLBs a word spans divided by the fewest it could span. | r3-method.tex:35 | r3-method.tex:35 | word; CLB | `split factor` |
| affinity packing (beta) | A copy of VPR's packer with a bonus beta for adding atoms of the same word or module to a cluster. | r3-method.tex:10 | norns.tex:153 | packing; purity | `affinity\|\\beta\|AAPack` |
| NMI | Normalised mutual information: how well one labelling predicts another. | r2-method.tex:59 | r2-method.tex:59 | cluster / clustering | `\bNMI\b` |
| compactness | Mean over labels of (CLBs of the label) / (tile area of the label's bounding box). | r2-method.tex:60 | r2-method.tex:60 | CLB | `compactness` |
| Rent exponent | How fast external connections grow with block count; a lower exponent is a more local design. | none | r2-method.tex:67 | netlist | `\bRent\b` |
| modularity Q | A graph score of how well a partition separates dense groups. | none | r2-method.tex:66 | cluster / clustering | `modularity\|\$Q\$` |
| geomean ratio | Geometric mean over designs of (variant / reference); below 1 favours the variant for lower-is-better metrics. | r2-method.tex:73 | r2-method.tex:73 | - | `geomean\|geometric mean` |
| sign test | Exact two-sided test on how many designs improve; ties are left out. | r2-method.tex:74 | r2-method.tex:74 | geomean ratio | `sign test` |
| Wilcoxon test | Rank test of per-design paired differences. | none | r3-results.tex:157 | geomean ratio | `Wilcoxon` |
| Holm adjustment | Correction of p-values for several simultaneous tests. | none | r3-results.tex:70 | Wilcoxon test | `\bHolm\b` |
| bootstrap interval | Confidence interval from resampling the designs. | none | r7-method.tex:24 | geomean ratio | `bootstrap` |
| decision rule / status | Pre-stated numeric rule that maps a result to supported, not supported or inconclusive. | r2-method.tex:72 | r2-method.tex:72 | geomean ratio | `decision rules?\|\bstatus` |
| pairing class | Class of a pair of atoms in one CLB: series-critical, series-noncritical, shared-input, orthogonal, filler. | r4-method.tex:24 | r4-method.tex:24 | CLB; critical path | `series-critical\|pair shares\|SC share` |
| known-by-construction clustering | A benchmark built from blocks that each fill one CLB, so the intended clustering is known (not a proven optimum). | r5-method.tex:5 | norns.tex:112 | CLB; cluster / clustering | `by construction\|known clustering\|known arm` |
| alignment a | How closely the HDL words match the intended blocks; 1 is the leak, 0 means words span about ten blocks. | r6-method.tex:4 | r6-method.tex:4 | word; known-by-construction clustering | `alignment` |
| leak | Gain that exists only because the HDL word file already equals the block partition. | r5-results.tex:64 | norns.tex:113 | alignment a | `\bleak` |
| hindsight clustering | Stock clustering with atoms moved or swapped between neighbouring CLBs according to where the best stock placement put them. | r7-appendix.tex:19 | norns.tex:113 | packing; placement | `hindsight` |
| flat-placement file | VPR's one-line-per-atom placement file (--read_flat_place) through which an outside placer enters VPR. | r8-results.tex:11 | norns.tex:115 | placement; VPR | `flat.place` |
| nextpnr (HeAP, SA) | An open-source FPGA placer with an analytic mode (HeAP) and an annealing mode (SA). | r8-results.tex:15 | norns.tex:115 | placement | `nextpnr\|HeAP` |
| reread control | The control that reads VPR's own final placement back into the default flow. | r8-results.tex:16 | r8-results.tex:16 | flat-placement file | `reread` |
| rule H0 | Adders, multipliers, RAMs and pads are fixed at VPR's analytic positions for the external placers. | r8-results.tex:25 | r8-results.tex:25 | nextpnr (HeAP, SA) | `Rule H0\|rule H0` |
| run record (Mimir) | A mimir-run.json per VPR or nextpnr run: commands, tool commits, parameters with their source, hashes. | r8-results.tex:71 | norns.tex:116 | VPR | `run records?\|mimir-run` |

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_evo_pipeline.schema import write_dataset_jsonl


CORE16_DOCS = {
    "0003",
    "0015",
    "0018",
    "0023",
    "0033",
    "0039",
    "0044",
    "0045",
    "0056",
    "0085",
    "0092",
    "0114",
    "0127",
    "0130",
    "0139",
    "0140",
}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def doc_no(case: dict) -> str:
    return str(case.get("case_id", "")).split("_")[-1].zfill(4)


def step(case: dict, idx: int) -> dict:
    for item in case.get("evolution_trajectory") or []:
        if int(item.get("step_index") or 0) == idx:
            return item
    raise KeyError(f"missing step {idx} in {case.get('case_id')}")


def note(case: dict, text: str) -> None:
    qc = case.setdefault("quality_control", {})
    notes = qc.setdefault("risk_notes", [])
    if isinstance(notes, list) and text not in notes:
        notes.append(text)


def patch_0015(case: dict) -> None:
    s = step(case, 4)
    s["next_step_reason"] = (
        "K477R supported retaining a more positively charged residue at site 477 for subsequent stabilizing combinations."
    )
    s5 = step(case, 5)
    s5["observation"] = "E445Q was screened out from the virtual-screening candidates with 13% improvement in cadaverine yield at 50 C and pH 8.0."
    s5["next_step_reason"] = (
        "K477R, F102V, and E445Q from directed evolution and virtual screening were combined with the previously reported T88S mutation."
    )
    s5["result_status"] = "success"
    s5["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0015/combined.md",
            "section": "Computational saturation mutagenesis of selected sites on the decamer interface of CadA",
            "quote_or_span": "virtual saturation mutagenesis was conducted for the above-mentioned sites instead using CUPSAT, iStable, and Rosetta-ddG",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0015/combined.md",
            "section": "Computational saturation mutagenesis of selected sites on the decamer interface of CadA",
            "quote_or_span": "Experimental verification was conducted for the candidate mutants predicted as positive by two algorithms or more.",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0015/combined.md",
            "section": "Computational saturation mutagenesis of selected sites on the decamer interface of CadA",
            "quote_or_span": "The mutant E445Q was screened out with 13% improvement in cadaverine yield at 50 °C and pH 8.0.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0015/combined.md",
            "section": "Combinatorial mutagenesis",
            "quote_or_span": "Based on the three positive mutations K477R, F102V, and E445Q identified in directed evolution and virtual screening, together with the previously reported T88S mutation",
        },
    ]
    note(case, "v9_targeted_repair: step4/5 narrowed CadA positive-charge and E445Q virtual-screening claims")


def patch_0004(case: dict) -> None:
    s = step(case, 2)
    s["decision"] = (
        "Construct an initial five-site NNK library, pick four 96-well plates of random variants, sequence them with LevSeq, and screen the 216 unique non-stop variants for cyclopropanation yield."
    )
    s["parameters"] = {
        "picked_variants": "four 96-well plates",
        "unique_variants_screened": 216,
        "sequencing_method": "LevSeq long-read pooled sequencing",
    }
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0004/combined.md",
            "section": "Using ALDE to efficiently optimize ParPgb for a non-native carbene transfer reaction",
            "quote_or_span": "Mutants in this library were generated through sequential rounds of PCR-based mutagenesis methods utilizing NNK degenerate codons.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0004/combined.md",
            "section": "Using ALDE to efficiently optimize ParPgb for a non-native carbene transfer reaction",
            "quote_or_span": "Four 96-well plates of these random variants were picked and sequenced using the LevSeq long-read pooled sequencing method",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0004/combined.md",
            "section": "Using ALDE to efficiently optimize ParPgb for a non-native carbene transfer reaction",
            "quote_or_span": "yielding 216 unique variants without stop codons.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0004/combined.md",
            "section": "Using ALDE to efficiently optimize ParPgb for a non-native carbene transfer reaction",
            "quote_or_span": "Screening revealed that nearly all of the variants had higher cyclopropanation activity than free-heme background activity",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0004/combined.md",
            "section": "Using ALDE to efficiently optimize ParPgb for a non-native carbene transfer reaction",
            "quote_or_span": "The ALDE computational package was used to train a predictive model on sequences and labels in the initial 216-member library",
        },
    ]
    note(case, "v10_targeted_repair: step2 distinguishes 384 picked wells from 216 unique screened variants")


def patch_0010(case: dict) -> None:
    s = step(case, 6)
    s["decision"] = (
        "Co-transform the computer-aided FECH mutant library and pHT into strain No. 20, screen at 280 ug/mL tetracycline, and select 20 isolates after five rounds."
    )
    s["observation"] = (
        "SH20 produced 7.48 mg/L heme, 2.04-fold wild type; its FECH carried Y26V, I29T, R30E, L43R, R46A, S222R, and E264L."
    )
    s["next_step_reason"] = "The authors then overexpressed ccmABC in SH20 to enhance heme export and reduce cytoplasmic heme toxicity."
    s["parameters"] = {"rounds": 5, "tetracycline_concentration": "280 ug/mL", "selected_isolates": 20}
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "hemH was mutated used mutation primer (Additional file 3: Table S3) in pALH, and the obtained mutant library and pHT were co-transformed into strain No. 20.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "The resulting mutant strains were sub-screened under screening pressure (280 $\\mu$ g/mL tetracycline) to enrich for high-heme-producing strains.",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "Twenty strains (named strains SH1–SH20, respectively) were randomly selected after five rounds of subculture for shaken-flask fermentation",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "the yield of strain SH20 reached 7.48 mg/L, which was 2.04-fold that of the wild type.",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "FECH in SH20 contained seven mutations compared with the wild type: Y26V, I29T, R30E, L43R, R46A, S222R, and E264L.",
        },
        {
            "evidence_id": "E35",
            "source_file": "docs/0010/combined.md",
            "section": "In vivo directed evolution of FECH for improved heme biosynthesis",
            "quote_or_span": "ccmABC, encoding a cytoplasmic to periplasmic heme transport protein, was overexpressed in strain SH20 to enhance heme export, thereby reducing the toxicity caused by excessive accumulation of heme in the cytoplasm",
        },
    ]
    note(case, "v12_targeted_repair: step6 grounds FECH screen, SH20 genotype, and ccmABC follow-up")


def patch_0021(case: dict) -> None:
    s = step(case, 6)
    s["decision"] = "Perform structural analysis using homology modeling."
    s["tool_or_method"] = {"category": "computational structural biology", "name": "Homology modeling", "version": ""}
    s["hypothesis"] = "P184C/M243C forms an intramolecular disulfide bond, while L218P reduces loop and random-coil flexibility."
    s["observation"] = (
        "The P184C/M243C disulfide increased PFL molecular stability, and the L218P proline substitution reduced loop and random-coil flexibility without loss of activity."
    )
    s["next_step_reason"] = "The structural analysis provided a mechanistic explanation for the observed PFL thermostability improvement."
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0021/combined.md",
            "section": "Structural Analysis of PFL and Its Mutants",
            "quote_or_span": "The homology model of PFL, which shows 47.2% identify with the lipase from Pseudomonas aeruginosa (PAL)",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0021/combined.md",
            "section": "Structural Analysis of PFL and Its Mutants",
            "quote_or_span": "The mutant P184C/M243C, which two has two additional cysteine residues, contained an intramolecular disulfide bond",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0021/combined.md",
            "section": "Structural Analysis of PFL and Its Mutants",
            "quote_or_span": "the variant lipase L218P decreased the flexibility of loops and enhanced the rigidity of the long random coil at high temperature.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0021/combined.md",
            "section": "Structural Analysis of PFL and Its Mutants",
            "quote_or_span": "The introduction of the disulfide bond between P184C and M243C increased the stability of the PFL molecule, while the substitution of proline reduced the flexibility of a loop and random coil without loss of enzyme activity.",
        },
    ]
    note(case, "v10_targeted_repair: step6 separates disulfide-mediated stability from proline-mediated flexibility reduction")


def patch_0044(case: dict) -> None:
    s4 = step(case, 4)
    s4["decision"] = (
        "Use T138G as the template for the methyl cinnamate trajectory and expand mutational exploration "
        "to CalB positions 39, 104, 190, 278, and 285 for subsequent library generations."
    )
    s4["observation"] = "Mutational exploration of the active-site cavity was expanded to positions 39, 104, 190, 278, and 285."
    s4["hypothesis"] = (
        "Additional active-site positions may provide mutations that combine beneficially with the G1 T138G template."
    )
    s4["tool_or_method"] = {"category": "library design", "name": "ISRD trajectory-guided library expansion", "version": ""}

    s5 = step(case, 5)
    s5["decision"] = (
        "Evaluate G2-selected mutations on successful G1 templates for the cinnamate and salicylate evolutionary trajectories."
    )
    s5["hypothesis"] = (
        "Adding selected G2 substitutions to active G1 backgrounds can identify additive double mutants for aromatic substrate transesterification."
    )
    s5["parameters"] = {
        "cinnamate_double_mutants": ["T138G-V190A", "T138G-D134S"],
        "salicylate_double_mutant": "V154L-L278A",
        "substrates": "vinyl cinnamate, vinyl salicylate",
    }
    s5["tool_or_method"] = {"category": "library screening", "name": "ISRD G2 library screening", "version": ""}
    s5["evidence"] = [
        {
            "evidence_id": "E04",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "the addition of G2-selected mutations (V190A and D134S) to the G1-T138G template allowed selection of double mutants displaying production yields nearly 6-fold",
        },
        {
            "evidence_id": "E20",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "we nevertheless selected a double mutant (V154L-L278A) exhibiting 3.6-fold increase in catalytic activity relative to WT CalB.",
        },
    ]

    s6 = step(case, 6)
    s6["decision"] = (
        "Use G1-G2 templates T138G-V190A and T138G-D134S for G3 active-site exploration and test whether further substitutions improve activity."
    )
    s6["parameters"] = {
        "templates": ["T138G-V190A", "T138G-D134S"],
        "reported_g3_substitutions": ["I189V", "I189L", "Q157L"],
    }
    s6["tool_or_method"] = {"category": "library screening", "name": "G3 active-site exploration", "version": ""}
    s6["evidence"] = [
        {
            "evidence_id": "E21",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "two initial G1-G2 templates were used for further active-site exploration: T138G-V190A and T138G-D134S",
        },
        {
            "evidence_id": "E22",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "amino acid replacements I189V, I189L, and Q157L were the only G3 substitutions providing increased synthetic activity relative to WT",
        },
        {
            "evidence_id": "E10",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "none of the G3 variants outperformed the best G2 candidates",
        },
    ]

    s7 = step(case, 7)
    s7["next_step_reason"] = (
        "The NMA/RIN result could partly explain the deleterious effect of D134S in the T138G-V190A background."
    )
    s7["parameters"] = {
        "mutants_compared": ["T138G-V190A", "T138G-V190A-D134S"],
    }
    s7["evidence"] = [
        {
            "evidence_id": "E23",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": (
                "Comparisons between the two energy-minimized structures of double mutant T138G-V190A and triple mutant "
                "T138G-V190A-D134S illustrate overall fold conservation and minimal structural perturbation in CalB"
            ),
        },
        {
            "evidence_id": "E24",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "This observation could partly explain the deleterious effects introduced by the D134S substitution in the context of otherwise beneficial mutations T138G-V190A.",
        },
    ]

    s8 = step(case, 8)
    s8["decision"] = "Perform ETA comparison of CalB active-site diversity and interpret selected variants against bulky vinyl ester substrates."
    s8["observation"] = (
        "ETA indicated that serine at positions 134, 138, and 189 or alanine at position 190 represented new unexplored natural-diversity solutions; smaller replacements in the most active variants helped accommodate bulky substrates."
    )
    s8["next_step_reason"] = "These findings support that ISRD uncovered productive CalB variants under substrate-specific selective pressure."
    s8["parameters"] = {
        "substrate_analogs": ["vinyl cinnamate", "vinyl salicylate"],
        "target_products": ["methyl cinnamate", "methyl salicylate"],
        "variants": ["T138G-V190A", "V154L-L278A"],
    }
    s8["evidence"] = [
        {
            "evidence_id": "E10",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "either serine at positions 134, 138 and 189 or alanine at position 190 represented two new unexplored solutions in the natural diversity",
        },
        {
            "evidence_id": "E25",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "smaller amino acid replacements were found in the most active variants, a mandatory requirement to accommodate bulkier substrates in the active-site cavity of CalB.",
        },
        {
            "evidence_id": "E26",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "binding predictions for the vinyl cinnamate and vinyl salicylate analogs",
        },
    ]
    note(case, "v11_targeted_repair: steps4-8 narrowed CalB G2/G3, NMA/RIN, and ETA substrate/product claims")


def patch_0045(case: dict) -> None:
    s5 = step(case, 5)
    s5["next_step_reason"] = "After identifying the best triple mutant, the paper summarized kinetic parameters and stability for IDI L141H/Y195F/W256C."
    s5["evidence"] = [
        {
            "evidence_id": "E35",
            "source_file": "docs/0045/combined.md",
            "section": "Site-directed saturation mutagenesis of residues L141, Y195, and W256",
            "quote_or_span": "Single, double and triple mutation enzymes were constructed to determine which were sufficient and necessary for enhanced IDI activity.",
        },
        {
            "evidence_id": "E36",
            "source_file": "docs/0045/combined.md",
            "section": "Site-directed saturation mutagenesis of residues L141, Y195, and W256",
            "quote_or_span": "Finally, the triple mutant L141H/Y195F/W256C showed the highest improvement (3.13-fold of wild type)",
        },
        {
            "evidence_id": "E37",
            "source_file": "docs/0045/combined.md",
            "section": "Kinetic characterization",
            "quote_or_span": "The kinetic parameters of IDI and triple-mutant IDI (L141H/Y195F/W256C) were summarized in Table 1.",
        },
        {
            "evidence_id": "E38",
            "source_file": "docs/0045/combined.md",
            "section": "Thermostability",
            "quote_or_span": "Mutants exhibited improved thermostability (Fig. 4b). Therefore, the thermostability of IDI (L141H/Y195F/W256C) was further analyzed",
        },
    ]

    s = step(case, 7)
    s["decision"] = (
        "Perform fed-batch fermentation with E. coli CHL-1 carrying wild-type IDI and CHL-2 carrying IDI L141H/Y195F/W256C."
    )
    s["observation"] = (
        "CHL-2 showed similar cell growth and substrate consumption to CHL-1, with lycopene production about 2.8-fold and final lycopene yield about 3.1-fold higher than CHL-1."
    )
    s["next_step_reason"] = "This fermentation validation showed that the triple-mutant IDI improved lycopene production in the expanded production system."
    s["parameters"] = {"strains": ["CHL-1 wild-type IDI", "CHL-2 IDI L141H/Y195F/W256C"]}
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0045/combined.md",
            "section": "Fed-batch fermentation",
            "quote_or_span": "the recombinant strain containing wild-type IDI was named CHL-1, and the recombinant strain containing IDI (L141H/Y195F/W256C) was named CHL-2.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0045/combined.md",
            "section": "Fed-batch fermentation",
            "quote_or_span": "Fed-batch fermentations were carried out to test the suitability and stability of IDI (L141H/Y195F/W256C) for the improved production of lycopene.",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0045/combined.md",
            "section": "Figure 5",
            "quote_or_span": "The cell growth rates of CHL-1 and CHL-2 were similar, and lycopene production of CHL-2 were approximately 2.8-fold of CHL-1.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0045/combined.md",
            "section": "Figure 5",
            "quote_or_span": "the substrate rates of CHL-1 and CHL-2 were similar, while final lycopene yield of CHL-2 was approximately 3.1-fold of CHL-1",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0045/combined.md",
            "section": "Discussion",
            "quote_or_span": "the strain CHL-2 had improved lycopene production compared to the original strain CHL-1, indicating that triple-mutant (L141H/Y195F/W256C) could translate improved enzymatic activity into the improvement of lycopene production successfully in an expanded system.",
        },
    ]
    note(case, "v7_targeted_repair: step7 uses figure-supported fermentation fold changes and fixes lycopene wording")


def patch_0056(case: dict) -> None:
    s = step(case, 6)
    s["decision"] = "Perform NMN+ reduction biotransformation with LY-13 variant and measure product formation over time."
    s["observation"] = "The LY-13 system achieved a total turnover number of approximately 45,000 with NMN+."
    s["parameters"] = {"cofactor": "NMN+", "enzyme": "LY-13 PTDH", "substrate": "phosphite"}
    s["evidence"] = [
        {
            "evidence_id": "E13",
            "source_file": "docs/0056/combined.md",
            "section": "Application of the engineered PTDHs in biocatalysis using noncanonical cofactors",
            "quote_or_span": "This PTDH-limited reaction system remained active for the entire 16 days it was observed, achieving a TTN of \\~45,000 with LY-13 (Fig. 4B)",
        }
    ]
    s7 = step(case, 7)
    s7["decision"] = "Test BNA+ mediated biotransformation with wild-type TS-PTDH, LY-7, and LY-13."
    s7["observation"] = (
        "At 20 mM BNA+ supplementation, LY-7 and LY-13 showed improved BNA+ utilization relative to wild-type TS-PTDH."
    )
    s7["parameters"] = {
        "cofactor": "BNA+",
        "variants": ["wild type TS-PTDH", "LY-7", "LY-13"],
        "BNA+ concentrations": "0, 5, 10, or 20 mM",
        "enzyme concentration": "10 uM TsOYE and appropriate TS-PTDH variant, each",
    }
    s7["evidence"] = [
        {
            "evidence_id": "E14",
            "source_file": "docs/0056/combined.md",
            "section": "BNA(H)-mediated PTDH biotransformation",
            "quote_or_span": (
                "When BNA $^{+}$ was reduced with wild type TS-PTDH, LY-7, and LY-13, a cofactor dose-dependent "
                "response in biotransformation efficiency was observed, and at 20 mM BNA $^{+}$ supplementation, "
                "LY-7 and LY-13 showed improved utilization of the BNA $^{+}$ relative to the wild type protein"
            ),
        },
        {
            "evidence_id": "E15",
            "source_file": "docs/0056/combined.md",
            "section": "BNA(H)-mediated PTDH biotransformation",
            "quote_or_span": "BNA $^{+}$ Cl $^{-}$ , prepared by refluxing equimolar amounts of nicotinamide and benzyl chloride in acetonitrile overnight, followed by precipitation with diethyl ether on ice $^{10}$ , was supplied to the reactions at final concentrations of 0, 5, 10, or 20 mM.",
        },
    ]
    note(case, "v5_targeted_repair: step6 corrected LY-6 to LY-13; step7 narrowed BNA+ variants to wild type, LY-7, and LY-13")


def patch_0069(case: dict) -> None:
    s = step(case, 4)
    s["decision"] = (
        "Pick the brightest blue/purple colony from the mCherry2 161X/163X library, sequence it, and characterize its spectra."
    )
    s["observation"] = (
        "The mCherry2-I161G/Q163G variant RDSmCherry0.1 had red-shifted excitation and emission maxima at 598 nm and 625 nm."
    )
    s["next_step_reason"] = "RDSmCherry0.1 was subjected to further engineering aimed at improving brightness and shifting excitation and emission further to the red."
    s["parameters"] = {"screen": "blue or purple colony appearance", "variant": "mCherry2-I161G/Q163G (RDSmCherry0.1)"}
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0069/combined.md",
            "section": "Results",
            "quote_or_span": "During screening of the mCherry2 161X/163X library it was noticed that a number of colonies appeared blue or purple to visual inspection.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0069/combined.md",
            "section": "Results",
            "quote_or_span": "The brightest of these colonies was picked and cultured for further analysis.",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0069/combined.md",
            "section": "Results",
            "quote_or_span": "Gene sequencing revealed this variant to be mCherry2-I161G/Q163G",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0069/combined.md",
            "section": "Results",
            "quote_or_span": "spectral analysis confirmed that it had a substantially red shifted fluorescence excitation and emission maxima at 598 nm and 625 nm, respectively.",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0069/combined.md",
            "section": "Results",
            "quote_or_span": "mCherry2-I161G/Q163G (designated as RDSmCherry0.1; Table 1) was subjected to further engineering aimed at improving the brightness and shifting the excitation and emission further to the red.",
        },
    ]
    note(case, "v8_targeted_repair: step4 uses explicit blue/purple-colony and RDSmCherry0.1 engineering evidence")


def patch_0083(case: dict) -> None:
    s = step(case, 4)
    s["decision"] = "Perform cassette saturation mutagenesis of I571 and V575 using NDT degenerate mutagenesis."
    s["hypothesis"] = "Mostly hydrophobic substitutions may be tolerated at I571 and V575, with I571C as an observed exception."
    s["observation"] = (
        "Only 12 of 590 screened clones were active. Active variants mostly retained hydrophobic substitutions except I571C; "
        "I571V and I571V-V575I were wild-type-like, I571F-V575L reduced EPA-CP5 about threefold, and I571C-V575I showed a moderate reduction."
    )
    s["next_step_reason"] = (
        "No library clone increased EPA-CP5 signal above the best wild-type controls; the strong hydrophobic preference at I571/V575 supports a hydrophobic acceptor-peptide binding surface."
    )
    s["parameters"] = {"target_codons": "I571 and V575 randomized using NDT degeneracy"}
    s["evidence"] = [
        {
            "evidence_id": "E20",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "Randomization was achieved with mutagenic primers bearing NDT degenerate codons",
        },
        {
            "evidence_id": "E21",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "Only 12 out of 590 screened library clones produced signals within the range of wild-type control clones",
        },
        {
            "evidence_id": "E22",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "With the exception of I571C, hydrophobic side chains were replaced by other hydrophobic side chains in active variants",
        },
        {
            "evidence_id": "E23",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "No significant difference to wild-type PglB was found for variants I571V and I571V-V575I, respectively",
        },
        {
            "evidence_id": "E24",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "The level of EPA-CP5 detected by ELISA was reduced by a factor of three in variant I571F-V575L",
        },
        {
            "evidence_id": "E25",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "The double mutant I571C-V575I was characterized by a parallel, moderate reduction in the levels of both EPA-CP5 and PglB",
        },
        {
            "evidence_id": "E26",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "None of the library clones exhibited increased EPA-CP5 ELISA signals compared to the top signal from wild-type clones",
        },
    ]
    note(case, "v6_targeted_repair: step4 qualified hydrophobic exception and double-mutant activity claims")


def patch_0092(case: dict) -> None:
    s = step(case, 4)
    s["next_step_reason"] = "The seven retested variants were then overexpressed and purified for kinetic characterization."
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0092/combined.md",
            "section": "Screening of FLS variants with improved DHA formation from single-site saturation mutation libraries",
            "quote_or_span": "the seven FLS variants demonstrating over a 2-fold improvement in DHA formation (S26F, G109I, S236F, S236L, H281Y, C398M, and C398A) were subjected to re-testing for whole-cell biocatalysis, with three biological replicates conducted.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0092/combined.md",
            "section": "Screening of FLS variants with improved DHA formation from single-site saturation mutation libraries",
            "quote_or_span": "These seven FLS variants exhibited higher activity to the original enzyme in terms of DHA formation, although the levels of improvement were not exactly the same as those observed during the initial round of screening",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0092/combined.md",
            "section": "Characterization of the selected FLS variants",
            "quote_or_span": "Seven FLS variants exhibiting over a 2-fold improvement in DHA formation (S26F, G109I, S236F, S236L, H281Y, C398M, and C398A) were overexpressed and purified to characterize their kinetic constants",
        },
    ]
    note(case, "v7_targeted_repair: step4 grounds transition from replicate retesting to kinetic characterization")


def patch_0104(case: dict) -> None:
    s = step(case, 2)
    s["decision"] = (
        "Sample D177, G178, and V240 with NNK codons while fixing I158S, then select on M9 agar plates containing 5 mM NMN+."
    )
    s["observation"] = (
        "LP 7 (I158S-D177W-V240L) and LP 3 (I158S-D177W-G178E-V240L) showed approximately 5-fold and 4-fold increases in NMNH specific activity, respectively, compared with wild-type Lp Nox."
    )
    s["next_step_reason"] = "The authors next sought to further improve LP 7 by targeting second-sphere residues L179, Q210, and M211."
    s["parameters"] = {
        "target_positions": ["D177", "G178", "V240"],
        "fixed_mutation": "I158S",
        "library_size": "~2.4e6 independent transformants",
        "selection_medium": "M9 minimal medium with 20 g/L D-glucose and 5 mM NMN+",
        "incubation_time": "10 days at 30 C",
    }
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0104/combined.md",
            "section": "Improving NMNH activity by targeting the first-sphere residues",
            "quote_or_span": "We sampled D177, G178, and V240 with NNK codons and fixed I158S.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0104/combined.md",
            "section": "Improving NMNH activity by targeting the first-sphere residues",
            "quote_or_span": "Selection was performed on agar plates with 20 g/L D-glucose in M9 minimal medium supplemented with 5 mM NMN $^{+}$ at 30 °C.",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0104/combined.md",
            "section": "Improving NMNH activity by targeting the first-sphere residues",
            "quote_or_span": "After incubation for 10 days, many colonies had formed on the selection plates.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0104/combined.md",
            "section": "Improving NMNH activity by targeting the first-sphere residues",
            "quote_or_span": "Variants LP 3 and LP 7 exhibited \\~4 and \\~5-fold increase of specific activity toward NMNH, respectively, compared to WT Lp Nox",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "We sought to further improve LP 7 by targeting residues L179, Q210, and M211 through another round of site-saturated mutagenesis and growth selection.",
        },
    ]
    s3 = step(case, 3)
    s3["decision"] = (
        "Construct pLS509 by site-saturation mutagenesis of LP 7 at L179, Q210, and M211, transform MX503, and perform growth selection without exogenous NMN+."
    )
    s3["observation"] = (
        "LP 7-1 (L179H-Q210C-M211W) improved specific activity from about 5500 to about 6600 nmol NMNH min-1 mg-1, and LP 7-2 showed about 30% residual activity after 23 h at 50 C versus about 19% for LP 7."
    )
    s3["next_step_reason"] = "In parallel, the authors used error-prone PCR on LP 3 to search a broader sequence space."
    s3["parameters"] = {
        "template": "LP 7",
        "target_positions": ["L179", "Q210", "M211"],
        "library": "pLS509",
        "selection_strain": "MX503",
        "exogenous_NMN+": "not added",
    }
    s3["evidence"] = [
        {
            "evidence_id": "E35",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "We sought to further improve LP 7 by targeting residues L179, Q210, and M211 through another round of site-saturated mutagenesis and growth selection.",
        },
        {
            "evidence_id": "E36",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "A site-saturated mutagenesis library (pLS509) with the NNK codon using LP 7 as the template was constructed and introduced in strain MX503.",
        },
        {
            "evidence_id": "E37",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "no exogenously supplied NMN $^{+}$ was added to the selection plates",
        },
        {
            "evidence_id": "E38",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "LP 7-1 represents a further improvement to LP 7 for specific activity, from \\~5500 to \\~6600 nmol NMNH min $^{-1}$ mg $^{-1}$",
        },
        {
            "evidence_id": "E39",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "LP 7-2 exhibited robust thermal stability with \\~30% residual activity remaining after 23 h of heat treatment at 50 °C, which is significantly higher than its parent variant LP 7 (\\~19% residual activity)",
        },
        {
            "evidence_id": "E40",
            "source_file": "docs/0104/combined.md",
            "section": "Restoring protein stability by targeting second-sphere residues",
            "quote_or_span": "In parallel to targeting the second sphere, we used error-prone PCR to search a broader protein sequence space, aiming to improve LP 3.",
        },
    ]
    note(case, "v10_targeted_repair: steps2/3 remove unsupported target and random-mutagenesis inference")


def patch_0112(case: dict) -> None:
    s = step(case, 5)
    s["observation"] = (
        "A64E R102S E323V has kcat/KM = 3.34 s-1mM-1 and total turnover number 65,900; "
        "it outperformed wild type and A64E in the total-turnover assay, while E323V is beneficial only in context."
    )
    s["evidence"] = [
        {
            "evidence_id": "E20",
            "source_file": "docs/0112/combined.md",
            "section": "Table 1",
            "quote_or_span": "A64E R102S E323V</td><td>4.23 ± 0.07</td><td>1.27 ± 0.07</td><td>3.34 ± 0.06</td><td>48.9 ± 0.09</td><td>98 ± 1.45</td><td>65,900 ± 380</td>",
        },
        {
            "evidence_id": "E11",
            "source_file": "docs/0112/combined.md",
            "section": "Results",
            "quote_or_span": "the variant A64E R102S E323V again outperforms not only the wild type but also mutation A64E by a wide margin",
        },
    ]
    note(case, "v5_targeted_repair: step5 corrected kinetic and TTN overclaim")


def patch_0122(case: dict) -> None:
    s2 = step(case, 2)
    s2["decision"] = "Create DNA shuffling Library 2 of approximately 500,000 variants and screen it with DMDS cooperative mode."
    s2["observation"] = (
        "Q30 (I209V/D211G/L257P) was the best Library 2 mutant; its R-ibuprofen-pNP ester enantioselectivity decreased from E_R=7.2 to E_R=3.0 and its S-ibuprofen-pNP ester catalytic activity increased twofold."
    )
    s2["next_step_reason"] = "The best mutant Q30 from Library 2 was used as the template for the next error-prone PCR Library 3."
    s2["parameters"] = {
        "library": "Library 2",
        "library_size": "approximately 500,000 variants",
        "screening_mode": "DMDS cooperative mode",
        "cell_occupancy": 0.1,
        "screened_droplets": 15000000,
    }
    s2["evidence"] = [
        {
            "evidence_id": "E20",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "The next round of directed evolution of afest consisted of shuffling of these nine mutation sites, generating a DNA shuffling library comprised of approximately 500,000 variants (Library 2).",
        },
        {
            "evidence_id": "E21",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "After one round of DMDS screening of this DNA shuffling library in cooperative mode",
        },
        {
            "evidence_id": "E22",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "a three-site mutant, Q30 (I209V/D211G/L257P), was identified as the best performing mutant variant",
        },
        {
            "evidence_id": "E23",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "Q30 outperformed wild-type AFEST: its enantioselectivity toward (R)-ibuprofen-pNP ester was decreased 2.4-fold (from $E_{R}=7.2$ to $E_{R}=3.0$",
        },
        {
            "evidence_id": "E24",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "showed a 2-fold increase in the catalytic activity for (S)-ibuprofen-pNP ester.",
        },
        {
            "evidence_id": "E25",
            "source_file": "docs/0122/combined.md",
            "section": "Methods",
            "quote_or_span": "Next, we screened Library 2 using the DMDS cooperative mode with a cell occupancy of 0.1 cells per droplet.",
        },
        {
            "evidence_id": "E26",
            "source_file": "docs/0122/combined.md",
            "section": "Methods",
            "quote_or_span": "Here, to achieve a 3× coverage, 15 million droplets were screened",
        },
        {
            "evidence_id": "E27",
            "source_file": "docs/0122/combined.md",
            "section": "Methods",
            "quote_or_span": "the best mutant (Q30) identified from Library 2 was used as the template for another round of error-prone PCR-based random mutagenesis",
        },
    ]

    s3 = step(case, 3)
    s3["parameters"] = {
        "library": "Library 3",
        "library_size": "2 million variants",
        "average_mutations": "2-4 mutated sites per variant",
        "screening_mode": "DMDS cooperative mode",
    }
    s3["next_step_reason"] = "IE9 shifted selectivity toward S but remained low, so the trajectory next amplified S-selectivity."
    s3["evidence"] = [
        {
            "evidence_id": "E23",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "This library was comprised of 2 million variants with 2–4 mutated sites per variant.",
        },
        {
            "evidence_id": "E05",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "As a consequence, the enantioselectivity of IE9 for (R)-ibuprofen-pNP ester was decreased 3.3-fold (from $E_{R}=3.0$ to $E_{S}=1.1$",
        },
    ]

    s5 = step(case, 5)
    s5["parameters"] = {
        "library": "Library 5",
        "library_size": "10,000 site-saturation mutant variants",
        "cell_occupancy": 0.05,
        "screening_mode": "DMDS biased mode",
    }
    s5["evidence"] = [
        {
            "evidence_id": "E24",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "These libraries were combined into a pooled library (Library 5) comprised of about 10,000 variants that was screened using the DMDS biased mode",
        },
        {
            "evidence_id": "E09",
            "source_file": "docs/0122/combined.md",
            "section": "Results",
            "quote_or_span": "the enantioselectivity of the 6A8 and 4D11 variants is 700-fold and 560-fold greater than wild-type AFEST",
        },
    ]
    note(case, "v5_targeted_repair: steps3/5 removed unsupported droplet-count and retained-fraction parameters")


def patch_0127(case: dict) -> None:
    s = step(case, 9)
    s["next_step_reason"] = (
        "Sequencing linked improved tyrosine production to novel aro4 mutations, motivating interpretation of which substitutions drove the phenotype."
    )
    s["evidence"] = [
        {
            "evidence_id": "E04",
            "source_file": "docs/0127/combined.md",
            "section": "Results",
            "quote_or_span": "The mutant aro4-9 derived from wild-type ARO4 (library 1) was 27-fold improved over wild-type and has three coding mutations (H230Y, K252N, and V262I;",
        },
        {
            "evidence_id": "E24",
            "source_file": "docs/0127/combined.md",
            "section": "Results",
            "quote_or_span": "The mutant aro4-229-9 derived from further mutagenesis of aro4-K229L (library 2) showed a 28-fold improvement over wild type and a 21% improvement relative to aro4-K229L, and has two additional coding mutations (T46A and T207I, Fig. 3f).",
        },
    ]
    note(case, "v5_targeted_repair: step9 corrected next_step_reason after fold improvements were already reported")


def patch_0130(case: dict) -> None:
    s4 = step(case, 4)
    s4["decision"] = "Sort a 5:95 model library of active CelA2-H288F and inactive CelA2-H288F-E580Q to validate enrichment."
    s4["observation"] = "Reanalysis of the sorted 5% model library showed a 5.3-fold enrichment of active events above gate P1."
    s4["next_step_reason"] = "The enrichment validated InVitroFlow because it isolated a significantly increased number of fluorescent events."
    s4["parameters"] = {
        "active_template": "CelA2-H288F",
        "inactive_template": "CelA2-H288F-E580Q",
        "active_to_inactive_ratio": "5:95",
        "event_rate": "1,500 events s^-1",
        "sorting_efficiency": "99.6%",
    }
    s4["evidence"] = [
        {
            "evidence_id": "E40",
            "source_file": "docs/0130/combined.md",
            "section": "Flow cytometry analysis and sorting",
            "quote_or_span": "Cell-free expressed DNA model libraries with an active-to-inactive ratio of 5:95 and 10:90 (CelA2-H288F $_{active}$ versus CelA2-H288F-E580Q $_{inactive}$ )",
        },
        {
            "evidence_id": "E41",
            "source_file": "docs/0130/combined.md",
            "section": "Figure 3",
            "quote_or_span": "5% model library (ratio 5:95 of CelA2-H288F $_{active}$ versus CelA2-H288F-E580Q $_{inactive}$ )",
        },
        {
            "evidence_id": "E42",
            "source_file": "docs/0130/combined.md",
            "section": "Flow cytometry analysis and sorting",
            "quote_or_span": "The library with an active-to-inactive ratio of 5 to 95 was sorted at an event rate of 1,500 events s $^{-1}$ with a sorting efficiency of 99.6%.",
        },
        {
            "evidence_id": "E43",
            "source_file": "docs/0130/combined.md",
            "section": "Flow cytometry analysis and sorting",
            "quote_or_span": "Reanalysis of the sorted fraction resulted in a 5.3-fold enrichment of the active emulsion fraction",
        },
        {
            "evidence_id": "E44",
            "source_file": "docs/0130/combined.md",
            "section": "Flow cytometry analysis and sorting",
            "quote_or_span": "The obtained enrichment validated the InVitroFlow technology platform since it is possible to isolate a significantly increased number of fluorescent events",
        },
    ]

    s = step(case, 6)
    s["decision"] = (
        "Recover sorted celA2-H288F library DNA, amplify it, clone it into pET28a(+), transform E. coli, and screen 528 variants in MTP with 4-MUC."
    )
    s["observation"] = (
        "MTP analysis found 33 improved cellulase variants; CelA2-H288F-M1, with N273D/N468S added to the H288F parent, showed 17.5-fold improvement for FDC/fluorescein and was the most beneficial variant."
    )
    s["next_step_reason"] = "CelA2-H288F-M1 was then purified and kinetically characterized."
    s["parameters"] = {
        "parent": "CelA2-H288F",
        "best_variant": "CelA2-H288F-M1 (N273D/H288F/N468S)",
        "substrate": "4-MUC",
        "variants_screened": 528,
    }
    s["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "optimized DNA recovery method based on NucleoSpin $^{\\circledR}$ Gel and PCR clean up kit (Macherey-Nagel) was used to isolate the DNA of the mutant library.",
        },
        {
            "evidence_id": "E31",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "After PCR amplification the PCR products of celA2 were analyzed using agarose-gelectrophoresis",
        },
        {
            "evidence_id": "E32",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "cloned into the pET28a(+) vector backbone via PLICing $^{32}$ , and transformed into E. coli BL21 Gold (DE3) for expression.",
        },
        {
            "evidence_id": "E33",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "In total, 528 cellulase variants were screened with the coumarin based 4-MUC activity quantification system in 96-well MTPs",
        },
        {
            "evidence_id": "E34",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "MTP analysis revealed 33 cellulase variants with significantly improved activity in comparison to the parent CelA2-H288F",
        },
        {
            "evidence_id": "E35",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "Analysis of variant CelA2-H288F-M1 showed 17.5-fold improvement for the pair FDC/fluorescein in comparison to the parent CelA2-H288F",
        },
        {
            "evidence_id": "E36",
            "source_file": "docs/0130/combined.md",
            "section": "Results",
            "quote_or_span": "CelA2-H288F-M1 (N273D/N468S) revealed to be the most beneficial cellulase variant",
        },
        {
            "evidence_id": "E37",
            "source_file": "docs/0130/combined.md",
            "section": "Kinetic characterization",
            "quote_or_span": "CelA2-H288F-M1</td><td>1.52 (±0.046)</td><td>9.66 (±1.19)</td><td>0.157</td><td>220.60 (±6.71)</td><td>N273D/H288F/N468S</td>",
        },
    ]
    note(case, "v9_targeted_repair: step6 includes H288F in best-variant identity and grounds recovery/MTP workflow")


def patch_0139(case: dict) -> None:
    s = step(case, 7)
    s["decision"] = (
        "Construct a homology model of beta-glucosidase, dock cellobiose, and use HMMTOP sequence-topology mapping to interpret cellodextrin transporter mutations."
    )
    s["hypothesis"] = (
        "L173H may create a new hydrogen bond with cellobiose; transporter mutations C82S and D433G may alter transmembrane-helix or loop features that affect uptake activity."
    )
    s["observation"] = (
        "H173 is predicted to form a hydrogen bond with the C1 hydroxyl of cellobiose; D433G is predicted on a large outside loop and C82S in the first transmembrane helix."
    )
    s["parameters"] = {
        "beta_glucosidase_analysis": "homology model with docked cellobiose",
        "transporter_analysis": "HMMTOP transmembrane topology prediction",
    }
    s["tool_or_method"] = {
        "category": "computational",
        "name": "Homology modeling and HMMTOP topology prediction",
        "version": "",
    }
    s["evidence"] = [
        {
            "evidence_id": "E07",
            "source_file": "docs/0139/combined.md",
            "section": "Discussion",
            "quote_or_span": "The mutated residue H173 is predicted to have a direct hydrogen bond with the hydroxyl group of the C1 atom of the cellobiose molecule.",
        },
        {
            "evidence_id": "E18",
            "source_file": "docs/0139/combined.md",
            "section": "Discussion",
            "quote_or_span": "a sequence-based analysis was performed with the aid of HMMTOP software",
        },
        {
            "evidence_id": "E19",
            "source_file": "docs/0139/combined.md",
            "section": "Discussion",
            "quote_or_span": "The D433G mutation is predicted to be located on the large outside loop and the C82S mutation is predicted to be in the first transmembrane helix.",
        },
    ]
    note(case, "v5_targeted_repair: step7 distinguished beta-glucosidase homology modeling from transporter HMMTOP mapping")


def patch_0152(case: dict) -> None:
    s = step(case, 1)
    s["next_step_reason"] = (
        "4NB1.2 improved selectivity but the paper proceeded with additional libraries and counter-selection to further improve the sensor."
    )
    s["evidence"] = [
        {
            "evidence_id": "E20",
            "source_file": "docs/0152/combined.md",
            "section": "Evolving a highly specific biosensor for 4'-O-Methylnorbelladine",
            "quote_or_span": "one variant bearing two amino acid substitutions (4NB1.2: K63T and L66M) displayed a 20-fold selectivity for 4NB over norbelladine",
        },
        {
            "evidence_id": "E21",
            "source_file": "docs/0152/combined.md",
            "section": "Evolving a highly specific biosensor for 4'-O-Methylnorbelladine",
            "quote_or_span": "Using 4NB1.2 as a starting point, additional libraries were generated that encompassed the other, previously randomized positions.",
        },
    ]
    note(case, "v5_targeted_repair: step1 grounded next_step_reason in additional-library/counter-selection trajectory")


def patch_0170(case: dict) -> None:
    s5 = step(case, 5)
    s5["decision"] = (
        "Introduce a low-copy plasmid encoding mCherry with upstream PT7 into YHM6, induce mutagenesis, and sort red-shifted variants by high 615:660 nm emission ratio."
    )
    s5["evidence"] = [
        {
            "evidence_id": "E30",
            "source_file": "docs/0170/combined.md",
            "section": "Results",
            "quote_or_span": "A low-copy plasmid encoding an mCherry expression cassette with upstream $P_{T7}$ for targeting (pCS4335) was introduced into strain YHM6.",
        },
        {
            "evidence_id": "E07",
            "source_file": "docs/0170/combined.md",
            "section": "Results",
            "quote_or_span": "From this initial library, we enriched for red-shifted variants by sorting the 1% of cells having the highest ratio of 615:660 nm emission",
        },
    ]
    s6 = step(case, 6)
    s6["decision"] = "Use YHM7 carrying PfDHFR and perform serial passages with increasing pyrimethamine concentration."
    s6["state_before"] = "TRIDENT was validated on fluorescent-protein screening; next test a growth-based drug-resistance selection."
    s6["evidence"].insert(
        0,
        {
            "evidence_id": "E31",
            "source_file": "docs/0170/combined.md",
            "section": "Results",
            "quote_or_span": "We designed a yeast strain, YHM7, that cannot grow in high concentrations of pyrimethamine by knocking out the essential, endogenous DHFR gene and replacing it with a P. falciparum DHFR gene expression cassette",
        },
    )
    note(case, "v5_targeted_repair: steps5/6 corrected mCherry plasmid workflow and YHM7 PfDHFR strain")


def patch_0183(case: dict) -> None:
    s = step(case, 7)
    s["observation"] = (
        "The four purified variants showed 20- to 35-fold increased kcat/KM for 2-NH and around 100-fold decreased paraoxon hydrolysis; improvements were mainly in kcat."
    )
    note(case, "v5_targeted_repair: step7 narrowed PTE activity decrease to around 100-fold for four characterized variants")


def patch_0192(case: dict) -> None:
    s6 = step(case, 6)
    s6["parameters"] = {
        "activity assay": "Casein (1%) in borate/NaOH pH 9.6, 2 mM CaCl2",
        "temperature range": "15｡紊 to 60｡紊",
    }
    s6["next_step_reason"] = "Activity and thermostability measurements established which variants merited mechanistic structural interpretation."

    s10 = step(case, 10)
    s10["observation"] = (
        "P9, A38, T162, and S182 were predicted to be exposed on the protein surface, while K27, A116, and T243 were buried; P9S may increase flexibility, T162S removes the H-bond to T159, and K27Q may alter local electrostatic potential."
    )
    s10["parameters"] = {}
    s10["evidence"] = [
        {
            "evidence_id": "E40",
            "source_file": "docs/0192/combined.md",
            "section": "Discussion",
            "quote_or_span": "the four substitution sites (P9, A38, T162, and S182) were predicated to be exposed on the protein surface.",
        },
        {
            "evidence_id": "E41",
            "source_file": "docs/0192/combined.md",
            "section": "Discussion",
            "quote_or_span": "The other three sites (K27, A116, and T243) were buried within the structural conformation of DHAP",
        },
        {
            "evidence_id": "E09",
            "source_file": "docs/0192/combined.md",
            "section": "Discussion",
            "quote_or_span": "Based on structural modeling, substitution of T162 with a serine residue led to loss of the H-bond to connect to T159 (Fig.",
        },
    ]
    note(case, "v5_targeted_repair: steps6/10 removed unsupported purification detail and corrected T162I to T162S")


PATCHERS = {
    "0004": patch_0004,
    "0010": patch_0010,
    "0015": patch_0015,
    "0021": patch_0021,
    "0044": patch_0044,
    "0045": patch_0045,
    "0056": patch_0056,
    "0069": patch_0069,
    "0083": patch_0083,
    "0092": patch_0092,
    "0104": patch_0104,
    "0112": patch_0112,
    "0122": patch_0122,
    "0127": patch_0127,
    "0130": patch_0130,
    "0139": patch_0139,
    "0152": patch_0152,
    "0170": patch_0170,
    "0183": patch_0183,
    "0192": patch_0192,
}


def write_pack(pack_dir: Path, cases: list[dict], *, label: str) -> None:
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True)
    write_dataset_jsonl(pack_dir / "dataset.jsonl", cases)
    (pack_dir / "samples_10.json").write_text(
        json.dumps(cases[:10], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary = {
        "label": label,
        "case_count": len(cases),
        "patched_docs": sorted(d for d in PATCHERS if any(doc_no(c) == d for c in cases)),
    }
    (pack_dir / "v12_patch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo V12 Hybrid Targeted Repair Pack

{label}

This pack applies targeted repairs from Top50 hybrid code+AI validation. Repairs only modify fields flagged by packet-level verification and preserve all unrelated trajectory content.
""",
        encoding="utf-8",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build V12 Top50 and Core16 hybrid-repaired packs.")
    parser.add_argument("--input-dataset", default=r"outputs\submission_top50\dataset.jsonl")
    parser.add_argument("--top50-dir", default=r"outputs\submission_top50_v12_hybrid_repaired")
    parser.add_argument("--core16-dir", default=r"outputs\submission_v12_core16_hybrid_repaired")
    args = parser.parse_args()

    cases = read_jsonl(Path(args.input_dataset))
    for case in cases:
        d = doc_no(case)
        if d in PATCHERS:
            PATCHERS[d](case)
            note(case, "v12_targeted_repair_applied")

    write_pack(Path(args.top50_dir), cases, label="Top50 repaired candidate set")
    core16 = [case for case in cases if doc_no(case) in CORE16_DOCS]
    core16.sort(key=lambda c: c.get("case_id", ""))
    write_pack(Path(args.core16_dir), core16, label="Core16 validation subset from the same V12 repaired data")
    print(json.dumps({"top50_count": len(cases), "core16_count": len(core16)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

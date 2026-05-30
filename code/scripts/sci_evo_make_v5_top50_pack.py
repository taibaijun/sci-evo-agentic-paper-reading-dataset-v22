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
    note(case, "v5_targeted_repair: step4 narrowed next_step_reason to evidence-supported K477R/positive-charge claim")


def patch_0021(case: dict) -> None:
    s = step(case, 6)
    s["decision"] = "Perform structural analysis using homology modeling."
    s["tool_or_method"] = {"category": "computational structural biology", "name": "Homology modeling", "version": ""}
    note(case, "v5_targeted_repair: step6 removed unsupported molecular-dynamics claim")


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

    s8 = step(case, 8)
    s8["observation"] = (
        "ETA indicated that serine at positions 134, 138, and 189 or alanine at position 190 represented new unexplored solutions in natural diversity; structural analysis related best variants to substrate accommodation."
    )
    s8["evidence"] = [
        {
            "evidence_id": "E10",
            "source_file": "docs/0044/combined.md",
            "section": "Results",
            "quote_or_span": "either serine at positions 134, 138 and 189 or alanine at position 190 represented two new unexplored solutions in the natural diversity",
        }
    ]
    note(case, "v5_targeted_repair: steps4-6/8 narrowed CalB G2/G3 and ETA claims to packet-supported evidence")


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


def patch_0083(case: dict) -> None:
    s = step(case, 4)
    s["decision"] = "Perform cassette saturation mutagenesis of I571 and V575 using NDT degenerate mutagenesis."
    s["parameters"] = {"target_codons": "I571 and V575 randomized using NDT degeneracy"}
    s["evidence"].insert(
        0,
        {
            "evidence_id": "E20",
            "source_file": "docs/0083/combined.md",
            "section": "Cassette mutagenesis of I571 and V575 (MIV motif)",
            "quote_or_span": "Randomization was achieved with mutagenic primers bearing NDT degenerate codons",
        },
    )
    note(case, "v5_targeted_repair: step4 corrected V575 codon description to NDT degeneracy")


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
    "0015": patch_0015,
    "0021": patch_0021,
    "0044": patch_0044,
    "0056": patch_0056,
    "0083": patch_0083,
    "0112": patch_0112,
    "0122": patch_0122,
    "0127": patch_0127,
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
    (pack_dir / "v5_patch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (pack_dir / "README.md").write_text(
        f"""# Sci-Evo V5 Hybrid Targeted Repair Pack

{label}

This pack applies targeted repairs from Top50 hybrid code+AI validation. Repairs only modify fields flagged by packet-level verification and preserve all unrelated trajectory content.
""",
        encoding="utf-8",
    )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build V5 Top50 and Core16 hybrid-repaired packs.")
    parser.add_argument("--input-dataset", default=r"outputs\submission_top50\dataset.jsonl")
    parser.add_argument("--top50-dir", default=r"outputs\submission_top50_v5_hybrid_repaired")
    parser.add_argument("--core16-dir", default=r"outputs\submission_v5_core16_hybrid_repaired")
    args = parser.parse_args()

    cases = read_jsonl(Path(args.input_dataset))
    for case in cases:
        d = doc_no(case)
        if d in PATCHERS:
            PATCHERS[d](case)
            note(case, "v5_targeted_repair_applied")

    write_pack(Path(args.top50_dir), cases, label="Top50 repaired candidate set")
    core16 = [case for case in cases if doc_no(case) in CORE16_DOCS]
    core16.sort(key=lambda c: c.get("case_id", ""))
    write_pack(Path(args.core16_dir), core16, label="Core16 validation subset from the same V5 repaired data")
    print(json.dumps({"top50_count": len(cases), "core16_count": len(core16)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

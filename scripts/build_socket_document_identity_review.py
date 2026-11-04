"""Stage 49: fail-closed source-document identity review for one socket SKU.

PDF mirrors, apparent redirects and self-reported product certifications never
constitute independent quality tests or permission to publish prices/tiers.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


SAFE_FLAGS = (
    "publishedPricesChanged",
    "flutterCalculationsChanged",
    "consumptionNormsChanged",
    "automaticPublicationEnabled",
    "automaticTierAssignmentEnabled",
)


def verify_url(url, host, mpn=None):
    if not isinstance(url, str):
        return False
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != host
            or parts.username or parts.password or parts.fragment):
        return False
    if mpn and mpn.lower() not in (parts.path + "?" + parts.query).lower():
        return False
    return True


def build(stage48, research, catalog, policy, readiness):
    if (stage48.get("status") != "socket_quality_comparison_research_only"
            or any(stage48.get(flag) is not False for flag in SAFE_FLAGS)):
        raise ValueError("Stage48 safety flags or source status changed")
    s = stage48.get("summary") or {}
    if (s.get("catalogMaterialsUntouched") != 41
            or s.get("manufacturerPartNumbersCompared") != 4
            or s.get("modelsEligibleForNextHumanDocumentReviewOnly") != 1
            or s.get("independentlyApprovedQualityTiers") != 0
            or s.get("verifiedLivePriceChanges") != 0):
        raise ValueError("Stage48 research counts or approval status changed")
    if (catalog.get("status") != "draft"
            or catalog.get("automaticUpdatesEnabled") is not False
            or len(catalog.get("materialPrices", {})) != 41
            or policy.get("enabled") is not False
            or policy.get("approvedMappings") != []
            or readiness.get("status") != "held"
            or readiness.get("policyEnabled") is not False
            or readiness.get("explicitPublicationApproved") is not False
            or readiness.get("approvedMappingCount") != 0
            or readiness.get("proposedPriceChanges") != 0):
        raise ValueError("Catalog publication gates must remain closed")
    models = stage48.get("models", [])
    if len(models) != 4 or len({x.get("mpn") for x in models}) != 4:
        raise ValueError("Model coverage changed")
    if any(x.get("approvedTier") is not None or x.get("approvedPriceChange") is not False
           or x.get("autoPublicationAllowed") is not False for x in models):
        raise ValueError("Stage48 product already approved")
    asfora = next((x for x in models if x["mpn"] == "EPH2900221"), None)
    if not asfora or asfora.get("reviewRoute") != "candidate_for_human_document_review_only":
        raise ValueError("Asfora research candidate is not eligible for document review")

    if (research.get("schemaVersion") != 1
            or research.get("status") != "manual_document_identity_research_only"
            or research.get("catalogMaterialKey") != "electricalSocketPerPiece"
            or research.get("manufacturerPartNumber") != "EPH2900221"):
        raise ValueError("Wrong Stage49 document lead configuration")
    product = research.get("officialManufacturerProductPage") or {}
    if (product.get("url") != asfora["officialManufacturerUrl"]
            or not verify_url(product.get("url"), "www.se.com", "EPH2900221")
            or product.get("observedPartNumberOnPage") != "EPH2900221"
            or product.get("observedGrounded2PPlusE") is not True
            or product.get("observedShutters") is not True
            or product.get("observedRatedAmperes") != 16
            or product.get("observedCompleteProduct") is not True
            or product.get("currentModelManufacturingStatusIndependentlyVerified") is not False):
        raise ValueError("Manufacturer product page data conflicts with Stage48")

    mirror = research.get("manufacturerBrandedDatasheetMirror") or {}
    traits = asfora.get("technicalTraitsAsAdvertisedNotIndependentlyTested") or {}
    if (not verify_url(mirror.get("url"), "solarshop.baywa-re.lv", "EPH2900221")
            or mirror.get("hostIsManufacturerControlled") is not False
            or mirror.get("manufacturerDocumentOriginalVerified") is not False
            or mirror.get("observedPartNumberOnDocument") != "EPH2900221"
            or mirror.get("historicalDocumentDateShown") != "2021-02-11"
            or mirror.get("observedGrounded2PPlusE") != traits.get("grounded2PPlusE")
            or mirror.get("observedShutters") != traits.get("shutters")
            or mirror.get("observedRatedAmperes") != traits.get("ratedAmperes")
            or mirror.get("observedRatedVolts") != traits.get("retailerDeclaredVolts")
            or mirror.get("observedIpClass") != traits.get("retailerDeclaredIp")
            or mirror.get("observedCompleteProduct") is not True
            or mirror.get("observedStandardMention") != "IEC 60884-1"
            or not mirror.get("observedCertificationNamesNotIndependentlyValidated")
            or mirror.get("dataNotCurrentIndependentLaboratoryProof") is not True):
        raise ValueError("Untrusted mirror or untraceable technical rating")

    compliance = research.get("officialComplianceDocumentRetrievalLead") or {}
    requested = compliance.get("requestedUrl")
    parts = urlsplit(requested) if isinstance(requested, str) else None
    query = parse_qs(parts.query) if parts else {}
    requested_mpn = compliance.get("requestedPartNumber")
    observed_mpn = compliance.get("observedReturnedDocumentPartNumber")
    if (not verify_url(requested, "download.se.com", "EPH2900221")
            or requested_mpn != "EPH2900221"
            or not query.get("p_Doc_Ref", [""])[0].startswith("EPH2900221_")
            or not isinstance(observed_mpn, str)
            or observed_mpn == requested_mpn
            or compliance.get("retrievalObservedDocumentIdentityConflict") is not True
            or compliance.get("observationIsNotProofOfManufacturerSiteFault") is not True
            or compliance.get("acceptedAsThisProductComplianceEvidence") is not False
            or not compliance.get("notesRu")):
        raise ValueError("Document redirect identity conflict must remain unapproved")
    if not research.get("remainingEvidenceRequirementsRu"):
        raise ValueError("Missing independent-documentation review gates")

    return {
        "schemaVersion": 1,
        "status": "asfora_exact_document_review_with_unresolved_provenance",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "researchDateNotCurrentDocumentVerification": research["capturedOnResearchDate"],
        **{flag: False for flag in SAFE_FLAGS},
        "summary": {
            "catalogMaterialsUntouched": 41,
            "socketModelsComparedPreviousStage": 4,
            "socketSkuDocumentAuditCases": 1,
            "matchingOfficialManufacturerProductPagesResearchOnly": 1,
            "manufacturerBrandedDatasheetMirrorsUnverified": 1,
            "complianceDocumentRetrievalIdentityConflicts": 1,
            "independentReliabilityLabTestsVerified": 0,
            "acceptedExactManufacturerDatasheets": 0,
            "approvedQualityTierMappings": 0,
            "approvedPriceChanges": 0,
        },
        "catalogMaterialKey": "electricalSocketPerPiece",
        "mpn": "EPH2900221",
        "companyProductUrl": product["url"],
        "observedInManufacturerWebpageNotIndependentLabEvidence": {
            "grounded": True, "shutters": True, "ratedAmperes": 16,
            "completeProduct": True,
        },
        "historicalThirdPartyDatasheetMirror": {
            "url": mirror["url"],
            "historicalDocumentDate": mirror["historicalDocumentDateShown"],
            "claimedStandardWithoutValidatedCurrentCertificate": mirror["observedStandardMention"],
            "claimedCertificationsNotIndependentlyValidated": list(mirror["observedCertificationNamesNotIndependentlyValidated"]),
            "ratedVolts": mirror["observedRatedVolts"],
            "ip": mirror["observedIpClass"],
            "trustedAsCurrentOriginal": False,
        },
        "complianceLinkRetrieval": {
            "requestedUrl": requested,
            "requestedMpn": requested_mpn,
            "observedOtherMpn": observed_mpn,
            "documentRejectedForProductApproval": True,
            "researchViewerResultRequiresManualRecheck": True,
            "notesRu": compliance["notesRu"],
        },
        "manualNextStepsRu": list(research["remainingEvidenceRequirementsRu"]),
        "moldovaPriceDateAndPhysicalStockVerified": False,
        "independentlyCertifiedQualityTier": None,
        "approvedPriceChange": False,
        "autoPublicationAllowed": False,
    }


def write_reports(report):
    Path("socket_document_identity_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        "# COSTARO — этап 49: проверка подлинности документов розетки", "",
        "**Исследование для человека. Не разрешает менять цены, нормы или уровни качества.**", "",
        f"- Точный артикул: **{report['mpn']}**.",
        f"- Страница производителя: {report['companyProductUrl']}",
        "- Страница описывает модель с заземлением, защитными шторками, 16 А и полную комплектацию.",
        "- Историческая копия фирменного технического PDF размещена не на сайте производителя:",
        f"  {report['historicalThirdPartyDatasheetMirror']['url']}",
        "- Указание IEC 60884-1, TSE, VDE или AENOR в таком PDF — не независимая проверка текущего сертификата.", "",
        "## Конфликт документа RoHS в исследовательском просмотре", "",
        f"- Запрашивался артикул `{report['complianceLinkRetrieval']['requestedMpn']}`.",
        f"- Наблюдался документ с другим артикулом `{report['complianceLinkRetrieval']['observedOtherMpn']}`.",
        "- Нельзя считать это действительным подтверждением запрошенной розетки.",
        "- Такая ошибка может относиться к просмотру/индексации, не обязательно к сайту Schneider.",
        f"- Проверить ссылку вручную: {report['complianceLinkRetrieval']['requestedUrl']}", "",
        "## Что должно быть проверено человеком", "",
    ]
    lines += [f"- [ ] {rule}" for rule in report["manualNextStepsRu"]]
    lines += ["", f"- Независимых лабораторных подтверждений: **{s['independentReliabilityLabTestsVerified']}**.",
              f"- Подтверждённых классов качества: **{s['approvedQualityTierMappings']}**.",
              f"- Изменений цен: **{s['approvedPriceChanges']}**.", ""]
    Path("socket_document_identity_review_RU.md").write_text("\n".join(lines), encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write("\n### COSTARO Stage 49 — документы Asfora\n\n")
            f.write("Один артикул; PDF с независимым подтверждением: **0**; "
                    "конфликт идентификатора при просмотре официального RoHS: **1**; "
                    "изменений цен и уровней качества: **0**.\n\n")


def main():
    paths = {
        "stage48": "socket_model_comparison.json",
        "research": "socket_asfora_document_leads.json",
        "catalog": "prices.json",
        "policy": "material_update_policy.json",
        "readiness": "verified_release_readiness.json",
    }
    inputs = {key: json.loads(Path(path).read_text(encoding="utf-8")) for key, path in paths.items()}
    report = build(**inputs)
    write_reports(report)
    print("COSTARO STAGE 49:", json.dumps(report["summary"], ensure_ascii=False))
    print("No approved datasheets, quality tiers, price changes, or automatic publication.")


if __name__ == "__main__":
    main()

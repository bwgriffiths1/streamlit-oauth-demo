You are extracting keywords from a NEPOOL meeting briefing for use in tracking and initiative management.

Review the briefing text below and extract 10–20 specific, meaningful keywords or short phrases that capture:
- Market mechanisms discussed (e.g., "Forward Capacity Market", "PFP settlement", "ADCR accreditation")
- Regulatory proceedings or docket references (e.g., "FERC ER24-1234", "tariff amendment")
- Rule changes or policy initiatives by name (e.g., "capacity accreditation reform", "dynamic reserve zones")
- Resource types or technologies that are the subject of discussion (e.g., "demand response", "offshore wind", "battery storage")
- Key dates or deadlines referenced (e.g., "FCA 19", "June 2026 effective date")

Do NOT include generic terms like "ISO-NE", "NEPOOL", "agenda item", "presentation", "meeting", or vague words like "update" or "discussion".

Return ONLY a valid JSON array of strings, with no preamble or explanation. Example format:
["Forward Capacity Market", "FCA 19", "ADCR accreditation", "PFP penalty provisions", "FERC ER25-500"]

Briefing text:
{briefing_text}

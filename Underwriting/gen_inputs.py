#!/usr/bin/env python3
"""Generate filled ACORD 125/140 PDFs using pdftk-java."""
import subprocess, os, tempfile

PDFTK = "java -jar /tmp/pdftk.jar"
BLANK_125 = "/home/ec2-user/.cache/gcp/Underwriting/Files/Blank_files/Acord125_Blank.pdf"
BLANK_140 = "/home/ec2-user/.cache/gcp/Underwriting/Files/Blank_files/Acord 140_Blank.pdf"
OUTPUT = "/home/ec2-user/.cache/gcp/Underwriting/Files/Input_Files"

def make_fdf(fields: dict) -> str:
    """Generate FDF content from field dict."""
    entries = []
    for k, v in fields.items():
        v_escaped = v.replace("(", "\\(").replace(")", "\\)")
        entries.append(f"<< /T ({k}) /V ({v_escaped}) >>")
    return f"""%FDF-1.2
1 0 obj
<< /FDF << /Fields [
{chr(10).join(entries)}
] >> >>
endobj
trailer
<< /Root 1 0 R >>
%%EOF"""

def fill_pdf(template, output, fields):
    fdf_content = make_fdf(fields)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.fdf', delete=False) as f:
        f.write(fdf_content)
        fdf_path = f.name
    cmd = f'{PDFTK} "{template}" fill_form "{fdf_path}" output "{output}"'
    subprocess.run(cmd, shell=True, capture_output=True)
    os.unlink(fdf_path)

SAMPLES = [
    {
        "folder": "Sample_A", "name": "Apex Manufacturing Corp",
        "f125": {
            "F[0].P1[0].Form_CompletionDate_A[0]": "05/10/2026",
            "F[0].P1[0].Producer_MailingAddress_LineOne_A[0]": "Marsh McLennan",
            "F[0].P1[0].Producer_MailingAddress_CityName_A[0]": "200 Park Ave, New York, NY 10166",
            "F[0].P1[0].Producer_ContactPerson_FullName_A[0]": "Robert Chen",
            "F[0].P1[0].Producer_ContactPerson_PhoneNumber_A[0]": "312-555-0147",
            "F[0].P1[0].Producer_ContactPerson_EmailAddress_A[0]": "rchen@marsh.com",
            "F[0].P1[0].Insurer_FullName_A[0]": "Zurich Insurance",
            "F[0].P1[0].Insurer_NAICCode_A[0]": "16535",
            "F[0].P1[0].Insurer_ProductDescription_A[0]": "COMMERCIAL PROPERTY",
            "F[0].P1[0].Policy_EffectiveDate_A[0]": "06/01/2026",
            "F[0].P1[0].Policy_ExpirationDate_A[0]": "06/01/2027",
            "F[0].P1[0].NamedInsured_FullName_A[0]": "Apex Manufacturing Corp",
            "F[0].P1[0].NamedInsured_MailingAddress_LineTwo_A[0]": "4500 Industrial Blvd, Chicago, IL 60632",
            "F[0].P1[0].NamedInsured_SICCode_A[0]": "3599",
            "F[0].P1[0].NamedInsured_NAICSCode_A[0]": "332710",
            "F[0].P1[0].NamedInsured_TaxIdentifier_A[0]": "36-4821567",
            "F[0].P1[0].NamedInsured_Primary_PhoneNumber_A[0]": "312-555-0147",
            "F[0].P2[0].NamedInsured_Contact_ContactDescription_A[0]": "VP OPERATIONS",
            "F[0].P2[0].NamedInsured_Contact_FullName_A[0]": "Robert Chen",
            "F[0].P2[0].NamedInsured_Contact_PrimaryPhoneNumber_A[0]": "312-555-0147",
            "F[0].P2[0].NamedInsured_Contact_PrimaryEmailAddress_A[0]": "rchen@apexmfg.com",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]": "4500 Industrial Blvd",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]": "Chicago",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]": "IL",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_PostalCode_A[0]": "60632",
            "F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]": "220",
            "F[0].P2[0].BusinessInformation_PartTimeEmployeeCount_A[0]": "100",
            "F[0].P4[0].LossHistory_InformationYearCount_A[0]": "5",
            "F[0].P4[0].LossHistory_TotalAmount_A[0]": "110000",
            "F[0].P4[0].LossHistory_OccurrenceDate_A[0]": "03/15/2025",
            "F[0].P4[0].LossHistory_LineOfBusiness_A[0]": "PROPERTY",
            "F[0].P4[0].LossHistory_OccurrenceDescription_A[0]": "Electrical fire in warehouse section B",
            "F[0].P4[0].LossHistory_ClaimDate_A[0]": "03/16/2025",
            "F[0].P4[0].LossHistory_PaidAmount_A[0]": "$85,000",
            "F[0].P4[0].LossHistory_ReservedAmount_A[0]": "$25,000",
        },
        "f140": {
            "Date": "05/10/2026", "Agency": "Marsh McLennan", "Applicant": "Apex Manufacturing Corp",
            "Carrier": "Zurich Insurance", "NAIC Code": "16535", "Effective Date": "06/01/2026",
            "Building #": "1", "Street Address": "4500 Industrial Blvd, Chicago, IL 60632",
            "Bldg Description": "Manufacturing facility with warehouse",
            "Subject of Insurance Line 1": "BUILDING", "Amount Line 1": "$2,500,000",
            "COINS Line 1": "80", "Valuation Line 1": "REPLACEMENT COST",
            "Causes of Loss Line 1": "SPECIAL", "DED Line 1": "5000",
            "Subject of Insurance Line 2": "BUSINESS PERSONAL PROPERTY", "Amount Line 2": "$1,500,000",
            "Construction Type": "NON-COMBUSTIBLE STEEL FRAME",
            "Hydrant FT": "150", "Fire Station MI": "3",
            "Prot CL": "4", "# Stories": "2", "Yr Built": "1998",
            "Total Area": "75000", "Roof Type": "METAL DECK",
            "Burglar Alarm type": "Central Station", "# Guards /Watchmen": "3",
            "Sprink": "80", "Fire alarm manufacturer": "Siemens", "Premises #": "1",
        }
    },
    {
        "folder": "Sample_B", "name": "Coastal Hospitality Group",
        "f125": {
            "F[0].P1[0].Form_CompletionDate_A[0]": "05/10/2026",
            "F[0].P1[0].Producer_MailingAddress_LineOne_A[0]": "Aon Risk Solutions",
            "F[0].P1[0].Producer_MailingAddress_CityName_A[0]": "200 E Randolph St, Chicago, IL 60601",
            "F[0].P1[0].Producer_ContactPerson_FullName_A[0]": "Sarah Mitchell",
            "F[0].P1[0].Producer_ContactPerson_PhoneNumber_A[0]": "305-555-0293",
            "F[0].P1[0].Producer_ContactPerson_EmailAddress_A[0]": "smitchell@aon.com",
            "F[0].P1[0].Insurer_FullName_A[0]": "Liberty Mutual Insurance",
            "F[0].P1[0].Insurer_ProductDescription_A[0]": "COMMERCIAL PROPERTY",
            "F[0].P1[0].Policy_EffectiveDate_A[0]": "03/15/2026",
            "F[0].P1[0].Policy_ExpirationDate_A[0]": "03/15/2027",
            "F[0].P1[0].NamedInsured_FullName_A[0]": "Coastal Hospitality Group",
            "F[0].P1[0].NamedInsured_MailingAddress_LineTwo_A[0]": "8900 Ocean Drive, Miami Beach, FL 33139",
            "F[0].P1[0].NamedInsured_SICCode_A[0]": "7011",
            "F[0].P1[0].NamedInsured_NAICSCode_A[0]": "721110",
            "F[0].P1[0].NamedInsured_TaxIdentifier_A[0]": "65-9876543",
            "F[0].P1[0].NamedInsured_Primary_PhoneNumber_A[0]": "305-555-0293",
            "F[0].P2[0].NamedInsured_Contact_ContactDescription_A[0]": "GENERAL MANAGER",
            "F[0].P2[0].NamedInsured_Contact_FullName_A[0]": "Maria Gonzalez",
            "F[0].P2[0].NamedInsured_Contact_PrimaryPhoneNumber_A[0]": "305-555-0188",
            "F[0].P2[0].NamedInsured_Contact_PrimaryEmailAddress_A[0]": "mgonzalez@coastalhospitality.com",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]": "8900 Ocean Drive",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]": "Miami Beach",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]": "FL",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_PostalCode_A[0]": "33139",
            "F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]": "350",
            "F[0].P2[0].BusinessInformation_PartTimeEmployeeCount_A[0]": "100",
            "F[0].P4[0].LossHistory_TotalAmount_A[0]": "360000",
            "F[0].P4[0].LossHistory_OccurrenceDate_A[0]": "09/10/2024",
            "F[0].P4[0].LossHistory_LineOfBusiness_A[0]": "PROPERTY",
            "F[0].P4[0].LossHistory_OccurrenceDescription_A[0]": "Hurricane wind damage to roof and exterior",
            "F[0].P4[0].LossHistory_ClaimDate_A[0]": "09/12/2024",
            "F[0].P4[0].LossHistory_PaidAmount_A[0]": "$220,000",
            "F[0].P4[0].LossHistory_ReservedAmount_A[0]": "$80,000",
            "F[0].P4[0].LossHistory_OccurrenceDate_B[0]": "01/05/2024",
            "F[0].P4[0].LossHistory_OccurrenceDescription_B[0]": "Guest slip and fall in lobby area",
            "F[0].P4[0].LossHistory_ClaimDate_B[0]": "01/06/2024",
            "F[0].P4[0].LossHistory_PaidAmount_B[0]": "$45,000",
            "F[0].P4[0].LossHistory_ReservedAmount_B[0]": "$15,000",
        },
        "f140": {
            "Date": "05/10/2026", "Agency": "Aon Risk Solutions", "Applicant": "Coastal Hospitality Group",
            "Carrier": "Liberty Mutual Insurance", "Effective Date": "03/15/2026",
            "Building #": "1", "Street Address": "8900 Ocean Drive, Miami Beach, FL 33139",
            "Bldg Description": "Luxury beachfront hotel and resort",
            "Subject of Insurance Line 1": "BUILDING", "Amount Line 1": "$8,500,000",
            "COINS Line 1": "90", "Valuation Line 1": "REPLACEMENT COST",
            "Causes of Loss Line 1": "SPECIAL", "DED Line 1": "10000",
            "Subject of Insurance Line 2": "BUSINESS PERSONAL PROPERTY", "Amount Line 2": "$3,500,000",
            "Construction Type": "FIRE-RESISTIVE REINFORCED CONCRETE",
            "Prot CL": "2", "# Stories": "12", "Yr Built": "2005",
            "Total Area": "180000", "Roof Type": "CONCRETE",
            "Burglar Alarm type": "Central Station", "# Guards /Watchmen": "6",
            "Sprink": "100", "Fire alarm manufacturer": "Honeywell", "Premises #": "1",
        }
    },
    {
        "folder": "Sample_C", "name": "Redwood Logistics LLC",
        "f125": {
            "F[0].P1[0].Form_CompletionDate_A[0]": "05/10/2026",
            "F[0].P1[0].Producer_MailingAddress_LineOne_A[0]": "AJG Gallagher",
            "F[0].P1[0].Producer_ContactPerson_FullName_A[0]": "David Park",
            "F[0].P1[0].Producer_ContactPerson_PhoneNumber_A[0]": "503-555-0421",
            "F[0].P1[0].Producer_ContactPerson_EmailAddress_A[0]": "dpark@ajg.com",
            "F[0].P1[0].Insurer_FullName_A[0]": "Travelers Insurance",
            "F[0].P1[0].Insurer_ProductDescription_A[0]": "COMMERCIAL PROPERTY",
            "F[0].P1[0].Policy_EffectiveDate_A[0]": "08/01/2026",
            "F[0].P1[0].Policy_ExpirationDate_A[0]": "08/01/2027",
            "F[0].P1[0].NamedInsured_FullName_A[0]": "Redwood Logistics LLC",
            "F[0].P1[0].NamedInsured_MailingAddress_LineTwo_A[0]": "2200 Harbor Way, Portland, OR 97201",
            "F[0].P1[0].NamedInsured_SICCode_A[0]": "4731",
            "F[0].P1[0].NamedInsured_NAICSCode_A[0]": "488510",
            "F[0].P1[0].NamedInsured_TaxIdentifier_A[0]": "93-1234567",
            "F[0].P1[0].NamedInsured_Primary_PhoneNumber_A[0]": "503-555-0421",
            "F[0].P2[0].NamedInsured_Contact_ContactDescription_A[0]": "OWNER",
            "F[0].P2[0].NamedInsured_Contact_FullName_A[0]": "David Park",
            "F[0].P2[0].NamedInsured_Contact_PrimaryPhoneNumber_A[0]": "503-555-0421",
            "F[0].P2[0].NamedInsured_Contact_PrimaryEmailAddress_A[0]": "dpark@redwoodlogistics.com",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]": "2200 Harbor Way",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]": "Portland",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]": "OR",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_PostalCode_A[0]": "97201",
            "F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]": "130",
            "F[0].P2[0].BusinessInformation_PartTimeEmployeeCount_A[0]": "50",
        },
        "f140": {
            "Date": "05/10/2026", "Agency": "AJG Gallagher", "Applicant": "Redwood Logistics LLC",
            "Carrier": "Travelers Insurance", "Effective Date": "08/01/2026",
            "Building #": "1", "Street Address": "2200 Harbor Way, Portland, OR 97201",
            "Bldg Description": "Warehouse and distribution center",
            "Subject of Insurance Line 1": "BUILDING", "Amount Line 1": "$1,800,000",
            "Subject of Insurance Line 2": "BUSINESS PERSONAL PROPERTY", "Amount Line 2": "$900,000",
            "Construction Type": "JOINTED MASONRY",
            "Prot CL": "5", "# Stories": "1", "Yr Built": "1985",
            "Total Area": "55000", "Roof Type": "BUILT-UP",
            "Burglar Alarm type": "Local", "# Guards /Watchmen": "2",
            "Sprink": "60", "Fire alarm manufacturer": "Edwards", "Premises #": "1",
        }
    },
    {
        "folder": "Sample_D", "name": "Summit Healthcare Systems",
        "f125": {
            "F[0].P1[0].Form_CompletionDate_A[0]": "05/10/2026",
            "F[0].P1[0].Producer_MailingAddress_LineOne_A[0]": "Willis Towers Watson",
            "F[0].P1[0].Producer_ContactPerson_FullName_A[0]": "Jennifer Walsh",
            "F[0].P1[0].Producer_ContactPerson_PhoneNumber_A[0]": "512-555-0876",
            "F[0].P1[0].Producer_ContactPerson_EmailAddress_A[0]": "jwalsh@wtwco.com",
            "F[0].P1[0].Insurer_FullName_A[0]": "The Hartford",
            "F[0].P1[0].Insurer_ProductDescription_A[0]": "COMMERCIAL PROPERTY",
            "F[0].P1[0].Policy_EffectiveDate_A[0]": "01/01/2026",
            "F[0].P1[0].Policy_ExpirationDate_A[0]": "01/01/2027",
            "F[0].P1[0].NamedInsured_FullName_A[0]": "Summit Healthcare Systems",
            "F[0].P1[0].NamedInsured_MailingAddress_LineTwo_A[0]": "700 Medical Center Pkwy, Austin, TX 78701",
            "F[0].P1[0].NamedInsured_SICCode_A[0]": "8062",
            "F[0].P1[0].NamedInsured_NAICSCode_A[0]": "622110",
            "F[0].P1[0].NamedInsured_TaxIdentifier_A[0]": "74-6329841",
            "F[0].P1[0].NamedInsured_Primary_PhoneNumber_A[0]": "512-555-0876",
            "F[0].P2[0].NamedInsured_Contact_ContactDescription_A[0]": "CFO",
            "F[0].P2[0].NamedInsured_Contact_FullName_A[0]": "Jennifer Walsh",
            "F[0].P2[0].NamedInsured_Contact_PrimaryPhoneNumber_A[0]": "512-555-0876",
            "F[0].P2[0].NamedInsured_Contact_PrimaryEmailAddress_A[0]": "jwalsh@summithealthcare.com",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]": "700 Medical Center Pkwy",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]": "Austin",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]": "TX",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_PostalCode_A[0]": "78701",
            "F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]": "500",
            "F[0].P2[0].BusinessInformation_PartTimeEmployeeCount_A[0]": "100",
        },
        "f140": {
            "Date": "05/10/2026", "Agency": "Willis Towers Watson", "Applicant": "Summit Healthcare Systems",
            "Carrier": "The Hartford", "Effective Date": "01/01/2026",
            "Building #": "1", "Street Address": "700 Medical Center Pkwy, Austin, TX 78701",
            "Bldg Description": "Medical center and hospital complex",
            "Subject of Insurance Line 1": "BUILDING", "Amount Line 1": "$12,000,000",
            "Subject of Insurance Line 2": "BUSINESS PERSONAL PROPERTY", "Amount Line 2": "$4,000,000",
            "Construction Type": "FIRE-RESISTIVE REINFORCED CONCRETE",
            "Prot CL": "2", "# Stories": "6", "Yr Built": "2012",
            "Total Area": "150000", "Roof Type": "CONCRETE",
            "Burglar Alarm type": "Central Station", "# Guards /Watchmen": "5",
            "Sprink": "100", "Fire alarm manufacturer": "Honeywell", "Premises #": "1",
        }
    },
    {
        "folder": "Sample_E", "name": "Pacific Auto Group",
        "f125": {
            "F[0].P1[0].Form_CompletionDate_A[0]": "05/10/2026",
            "F[0].P1[0].Producer_MailingAddress_LineOne_A[0]": "Lockton Companies",
            "F[0].P1[0].Producer_ContactPerson_FullName_A[0]": "Kevin Tanaka",
            "F[0].P1[0].Producer_ContactPerson_PhoneNumber_A[0]": "415-555-0632",
            "F[0].P1[0].Producer_ContactPerson_EmailAddress_A[0]": "ktanaka@lockton.com",
            "F[0].P1[0].Insurer_FullName_A[0]": "CHUBB Insurance",
            "F[0].P1[0].Insurer_ProductDescription_A[0]": "COMMERCIAL PROPERTY",
            "F[0].P1[0].Policy_EffectiveDate_A[0]": "04/01/2026",
            "F[0].P1[0].Policy_ExpirationDate_A[0]": "04/01/2027",
            "F[0].P1[0].NamedInsured_FullName_A[0]": "Pacific Auto Group",
            "F[0].P1[0].NamedInsured_MailingAddress_LineTwo_A[0]": "1500 El Camino Real, San Francisco, CA 94080",
            "F[0].P1[0].NamedInsured_SICCode_A[0]": "5511",
            "F[0].P1[0].NamedInsured_NAICSCode_A[0]": "441110",
            "F[0].P1[0].NamedInsured_TaxIdentifier_A[0]": "94-7654321",
            "F[0].P1[0].NamedInsured_Primary_PhoneNumber_A[0]": "415-555-0632",
            "F[0].P2[0].NamedInsured_Contact_ContactDescription_A[0]": "OWNER",
            "F[0].P2[0].NamedInsured_Contact_FullName_A[0]": "Kevin Tanaka",
            "F[0].P2[0].NamedInsured_Contact_PrimaryPhoneNumber_A[0]": "415-555-0632",
            "F[0].P2[0].NamedInsured_Contact_PrimaryEmailAddress_A[0]": "ktanaka@pacificauto.com",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]": "1500 El Camino Real",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]": "San Francisco",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]": "CA",
            "F[0].P2[0].CommercialStructure_PhysicalAddress_PostalCode_A[0]": "94080",
            "F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]": "65",
            "F[0].P2[0].BusinessInformation_PartTimeEmployeeCount_A[0]": "30",
            "F[0].P4[0].LossHistory_TotalAmount_A[0]": "225000",
            "F[0].P4[0].LossHistory_OccurrenceDate_A[0]": "10/17/2023",
            "F[0].P4[0].LossHistory_LineOfBusiness_A[0]": "PROPERTY",
            "F[0].P4[0].LossHistory_OccurrenceDescription_A[0]": "Earthquake damage to showroom glass and structure",
            "F[0].P4[0].LossHistory_ClaimDate_A[0]": "10/18/2023",
            "F[0].P4[0].LossHistory_PaidAmount_A[0]": "$175,000",
            "F[0].P4[0].LossHistory_ReservedAmount_A[0]": "$50,000",
        },
        "f140": {
            "Date": "05/10/2026", "Agency": "Lockton Companies", "Applicant": "Pacific Auto Group",
            "Carrier": "CHUBB Insurance", "Effective Date": "04/01/2026",
            "Building #": "1", "Street Address": "1500 El Camino Real, San Francisco, CA 94080",
            "Bldg Description": "Auto dealership showroom and service center",
            "Subject of Insurance Line 1": "BUILDING", "Amount Line 1": "$3,200,000",
            "Subject of Insurance Line 2": "INVENTORY - VEHICLES", "Amount Line 2": "$5,800,000",
            "Construction Type": "NON-COMBUSTIBLE STEEL FRAME",
            "Prot CL": "3", "# Stories": "1", "Yr Built": "2001",
            "Total Area": "35000", "Roof Type": "METAL DECK",
            "Burglar Alarm type": "Central Station", "# Guards /Watchmen": "2",
            "Sprink": "90", "Fire alarm manufacturer": "Notifier", "Premises #": "1",
        }
    },
]

for s in SAMPLES:
    folder = os.path.join(OUTPUT, s["folder"])
    os.makedirs(folder, exist_ok=True)
    fill_pdf(BLANK_125, os.path.join(folder, f"Acord125_{s['folder']}.pdf"), s["f125"])
    fill_pdf(BLANK_140, os.path.join(folder, f"Acord140_{s['folder']}.pdf"), s["f140"])
    print(f"  {s['folder']}: {s['name']}")

print("\nDone. 5 samples generated.")

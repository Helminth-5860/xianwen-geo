import townData from "@province-city-china/town";

type TownNode = Readonly<{
  code: string;
  name: string;
  town: string | 0;
}>;

type TownOption = Readonly<{ value: string; label: string }>;

const DISTRICT_CODE = /^\d{6}$/;
const townsByDistrict = new Map<string, TownOption[]>();

for (const item of townData as readonly TownNode[]) {
  if (typeof item.town !== "string") continue;
  const option = { value: `${item.code}${item.town}`, label: item.name };
  const existing = townsByDistrict.get(item.code);
  if (existing) existing.push(option);
  else townsByDistrict.set(item.code, [option]);
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ districtCode: string }> },
) {
  const { districtCode } = await params;
  if (!DISTRICT_CODE.test(districtCode)) {
    return Response.json({ error: "INVALID_DISTRICT_CODE" }, { status: 400 });
  }
  return Response.json(
    { district_code: districtCode, towns: townsByDistrict.get(districtCode) ?? [] },
    {
      headers: {
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
      },
    },
  );
}

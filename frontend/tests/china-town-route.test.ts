import { describe, expect, it } from "vitest";

import { GET } from "../app/region-data/towns/[districtCode]/route";

describe("town data route", () => {
  it("returns only the selected district with stable street codes", async () => {
    const response = await GET(new Request("http://localhost/region-data/towns/110101"), {
      params: Promise.resolve({ districtCode: "110101" }),
    });
    const payload = (await response.json()) as {
      district_code: string;
      towns: Array<{ value: string; label: string }>;
    };

    expect(response.status).toBe(200);
    expect(payload.district_code).toBe("110101");
    expect(payload.towns).toContainEqual({ value: "110101001000", label: "东华门街道" });
    expect(payload.towns.every((item) => item.value.startsWith("110101"))).toBe(true);
  });

  it("rejects invalid district codes", async () => {
    const response = await GET(new Request("http://localhost/region-data/towns/bad"), {
      params: Promise.resolve({ districtCode: "bad" }),
    });
    expect(response.status).toBe(400);
  });
});

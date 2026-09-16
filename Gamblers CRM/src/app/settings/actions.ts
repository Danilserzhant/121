"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { db } from "@/lib/db";

const sourceSchema = z.object({
  slug: z.string().min(2).max(64).regex(/^[a-z0-9-]+$/, "только латиница, цифры и дефис"),
  title: z.string().min(2).max(120),
  kind: z.enum(["blogger", "ads", "seeding", "organic", "partner", "other"]),
  spend: z.string().optional(),
  currency: z.string().min(3).max(3).default("USD"),
});

export async function createSource(_prev: { error?: string } | null, formData: FormData) {
  const parsed = sourceSchema.safeParse({
    slug: String(formData.get("slug") ?? "").trim(),
    title: String(formData.get("title") ?? "").trim(),
    kind: String(formData.get("kind") ?? "other"),
    spend: String(formData.get("spend") ?? "").trim(),
    currency: String(formData.get("currency") ?? "USD").toUpperCase(),
  });
  if (!parsed.success) return { error: parsed.error.issues[0]?.message ?? "Проверьте поля" };

  const spend = parsed.data.spend ? Number(parsed.data.spend.replace(",", ".")) : null;
  if (spend !== null && !Number.isFinite(spend)) return { error: "Расход должен быть числом" };

  const exists = await db.source.findUnique({ where: { slug: parsed.data.slug } });
  if (exists) return { error: "Источник с таким slug уже есть" };

  await db.source.create({
    data: {
      slug: parsed.data.slug,
      title: parsed.data.title,
      kind: parsed.data.kind,
      spend,
      currency: parsed.data.currency,
    },
  });
  revalidatePath("/settings");
  revalidatePath("/sources");
  return {};
}

export async function updateSourceSpend(formData: FormData) {
  const id = Number(formData.get("id"));
  const raw = String(formData.get("spend") ?? "").trim();
  const spend = raw === "" ? null : Number(raw.replace(",", "."));
  if (!Number.isFinite(id) || (spend !== null && !Number.isFinite(spend))) return;
  await db.source.update({ where: { id }, data: { spend } });
  revalidatePath("/settings");
  revalidatePath("/sources");
}

/** Привязка пригласительной ссылки к источнику — основа атрибуции трафика. */
export async function assignLinkSource(formData: FormData) {
  const linkId = Number(formData.get("linkId"));
  const raw = String(formData.get("sourceId") ?? "");
  const sourceId = raw === "" ? null : Number(raw);
  if (!Number.isFinite(linkId)) return;

  await db.$transaction([
    db.inviteLink.update({ where: { id: linkId }, data: { sourceId } }),
    // Переклеиваем источник у всех, кто уже пришёл по этой ссылке.
    db.membership.updateMany({ where: { inviteLinkId: linkId }, data: { sourceId } }),
  ]);
  revalidatePath("/settings");
  revalidatePath("/sources");
  revalidatePath("/");
}

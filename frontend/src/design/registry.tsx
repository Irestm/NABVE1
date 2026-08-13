import { CalmCloudBackground, CalmCloudDesign } from "./CalmCloudDesign";
import { ClownBackground, ClownDesign } from "./ClownDesign";
import { EyeBackground, EyeDesign } from "./EyeDesign";
import { GreenCloudBackground, GreenCloudDesign } from "./GreenCloudDesign";
import { PixelBackground, PixelDesign } from "./PixelDesign";
import { StandardDesign } from "./StandardDesign";
import { SunBackground, SunDesign } from "./SunDesign";
import type { DesignDefinition, DesignId } from "./types";

export const DEFAULT_DESIGN_ID: DesignId = "standard";

export const DESIGNS: DesignDefinition[] = [
  {
    id: "sun",
    name: "Живое Солнце",
    tagline: "Дышит и разрастается от твоего голоса",
    description:
      "Настоящая маленькая звезда с гранулированной поверхностью и солнечными вспышками — корона расширяется пропорционально громкости голоса.",
    Component: SunDesign,
    Background: SunBackground,
  },
  {
    id: "clown",
    name: "Клоун-Пищалка",
    tagline: "Нажми на нос — не удержишься",
    description:
      "Рыжий клоунский парик по бокам и красный нос по центру. Нажми на нос — он пискнет и на секунду взорвётся всеми цветами радуги.",
    Component: ClownDesign,
    Background: ClownBackground,
  },
  {
    id: "cloud_green",
    name: "Изумрудный Пар",
    tagline: "Дух в бутылке, а не ассистент",
    description: "Зелёные испарения клубятся и поднимаются вверх, будто в лампе поселился джинн.",
    Component: GreenCloudDesign,
    Background: GreenCloudBackground,
  },
  {
    id: "pixel",
    name: "Пиксельное Ядро",
    tagline: "Максимально плотная 8-битная мозаика",
    description: "Плотная сетка мерцающих пикселей без единого зазора — цифровой дух из старой аркады.",
    Component: PixelDesign,
    Background: PixelBackground,
  },
  {
    id: "eye",
    name: "Всевидящее Око",
    tagline: "Анатомия без прикрас — и курсор под стать",
    description:
      "Реалистичный глаз с сосудами и радужкой, зрачок расширяется от громкости. Курсор превращается в отрубленную руку, а обод вокруг ока сплетён из нервных волокон.",
    Component: EyeDesign,
    Background: EyeBackground,
  },
  {
    id: "cloud_calm",
    name: "Облако Спокойствия",
    tagline: "Тихая гавань для тех, кому не до фейерверков",
    description: "Мягкое пастельное облако, плавно покачивается и мерцает звёздочками. Реагирует едва заметно.",
    Component: CalmCloudDesign,
    Background: CalmCloudBackground,
  },
  {
    id: "standard",
    name: "Классика",
    tagline: "Оригинальный HUD-шар",
    description: "Тот самый шар с кольцами и разверткой радара, с которого всё начиналось. Надёжно и без сюрпризов.",
    Component: StandardDesign,
  },
];

export function getDesign(id: DesignId): DesignDefinition {
  return DESIGNS.find((design) => design.id === id) ?? DESIGNS[DESIGNS.length - 1];
}

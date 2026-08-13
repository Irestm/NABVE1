import { CentralOrb } from "../components/CentralOrb";
import type { DesignComponentProps } from "./types";

export function StandardDesign({ state }: DesignComponentProps): JSX.Element {
  return <CentralOrb state={state} />;
}

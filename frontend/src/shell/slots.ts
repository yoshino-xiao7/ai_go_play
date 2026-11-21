import { createContext, useContext } from "react";

/**
 * Top-bar portal hosts owned by the shell. The elements are rendered unconditionally at fixed
 * positions, so their DOM identity outlives any view that portals into them; views receive the
 * real nodes through this context instead of looking them up by id.
 */
export type ShellSlots = { project: HTMLElement | null; status: HTMLElement | null };
export const ShellSlotsContext = createContext<ShellSlots>({ project: null, status: null });
export const useShellSlots = () => useContext(ShellSlotsContext);

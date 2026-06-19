"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * Wraps the app in next-themes so we get system/light/dark with no flash.
 * Strategy is "class" (see tailwind.config.ts darkMode), which toggles the
 * `dark` class on <html>.
 */
export function ThemeProvider({ children }: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}

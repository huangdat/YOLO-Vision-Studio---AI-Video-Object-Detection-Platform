import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

/** Renders the current location so tests can assert URL-driven state. */
function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

export function renderAt(path: string, routePath: string, element: ReactElement) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path={routePath} element={element} />
        <Route path="*" element={<p>Other route</p>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
}

export function currentLocation(container: HTMLElement): string {
  return container.ownerDocument.querySelector('[data-testid="location"]')?.textContent ?? "";
}

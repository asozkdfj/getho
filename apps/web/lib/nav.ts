/**
 * Whether a menu item is the current section. Fixture pages belong to "경기"
 * (they are reached from the match list); everything else matches by prefix.
 */
export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname.startsWith("/fixtures");
  return pathname === href || pathname.startsWith(`${href}/`);
}

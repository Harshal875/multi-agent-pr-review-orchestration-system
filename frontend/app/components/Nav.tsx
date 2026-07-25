"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Reviews" },
  { href: "/hitl", label: "Approval Queue" },
  { href: "/economics", label: "Economics" },
];

export default function Nav() {
  const path = usePathname();
  return (
    <nav className="nav">
      <div className="brand">AI PR<span>·</span>Review</div>
      {links.map((l) => (
        <Link key={l.href} href={l.href}
          className={path === l.href ? "active" : ""}>{l.label}</Link>
      ))}
    </nav>
  );
}

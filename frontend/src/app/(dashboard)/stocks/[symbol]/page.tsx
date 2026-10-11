import { StockDetail } from "@/components/pages";
export default async function Page({
  params,
}: {
  params: Promise<{ symbol: string }>;
}) {
  const { symbol } = await params;
  return <StockDetail symbol={symbol.toUpperCase()} />;
}

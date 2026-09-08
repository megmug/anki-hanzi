<script lang="ts">
	/**
	 * One product tile: picture, price, and the two things a shopper does —
	 * read more, or buy.
	 *
	 * The picture is a card screenshot from `npm run shoot:card-previews`, which
	 * is run by hand against a real Anki profile. Those files are not in the repo,
	 * so a missing one must not leave a broken image in the grid: `failed` flips
	 * on the img's `onerror` and the tile below it — the product's own glyph on a
	 * tinted ground — takes over. Dropping the JPG into `static/img/shop/` later
	 * is the whole change.
	 */
	import {
		buyUrl,
		formatPrice,
		isUnpriced,
		priceUnit,
		productImage,
		tileGlyph,
		type ShopManifest,
		type ShopProduct
	} from '$lib/shop';
	import { btnPrimary, btnSecondary } from '$lib/buttonStyles';
	import ShoppingBag from '@lucide/svelte/icons/shopping-bag';

	let {
		manifest,
		product,
		onDetails
	}: {
		manifest: ShopManifest;
		product: ShopProduct;
		onDetails: (product: ShopProduct) => void;
	} = $props();

	let failed = $state(false);

	const src = $derived(productImage(product));
	const href = $derived(buyUrl(manifest, product));
</script>

<article
	class="flex flex-col overflow-hidden rounded-xl border border-neutral-200 bg-white transition hover:border-neutral-900 hover:shadow-[4px_4px_0_0_#111]"
>
	<!-- Picture. Fixed aspect so a missing shot and a real one leave the grid
	     the same shape. -->
	<div class="relative aspect-[4/3] overflow-hidden border-b border-neutral-200 bg-neutral-50">
		{#if src && !failed}
			<img
				{src}
				alt={product.imageAlt || product.name}
				loading="lazy"
				onerror={() => (failed = true)}
				class="h-full w-full object-cover object-top"
			/>
		{:else}
			<div
				class="flex h-full w-full items-center justify-center bg-gradient-to-br from-neutral-100 to-neutral-200"
			>
				<span class="text-7xl font-light text-neutral-400" lang="zh-Hans">{tileGlyph(product)}</span>
			</div>
		{/if}
		{#if product.badge}
			<span
				class="absolute left-3 top-3 rounded-full bg-neutral-900 px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider text-white"
			>
				{product.badge}
			</span>
		{/if}
	</div>

	<div class="flex flex-1 flex-col p-5">
		<h3 class="font-semibold leading-snug">{product.name}</h3>
		<p class="mt-1.5 text-sm leading-relaxed text-neutral-600">{product.tagline}</p>

		<!-- Price sits above the buttons and takes the weight: it is the one
		     number a shopper is looking for. -->
		<div class="mt-4 flex items-baseline gap-1.5">
			<span
				class={isUnpriced(product.price)
					? 'text-sm font-medium text-neutral-500'
					: 'text-2xl font-bold tracking-tight'}
			>
				{formatPrice(product.price, manifest.currency)}
			</span>
			{#if priceUnit(product.price)}
				<span class="font-mono text-xs uppercase tracking-wider text-neutral-400">
					{priceUnit(product.price)}
				</span>
			{/if}
		</div>

		<div class="mt-auto flex flex-wrap items-center gap-2 pt-4">
			<a
				class="{btnPrimary} inline-flex items-center gap-2"
				{href}
				target="_blank"
				rel="noopener noreferrer"
			>
				<ShoppingBag size={15} /> Buy on Patreon
			</a>
			<button type="button" class={btnSecondary} onclick={() => onDetails(product)}>
				See more details
			</button>
		</div>
	</div>
</article>

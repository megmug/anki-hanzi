<script lang="ts">
	/**
	 * The shop.
	 *
	 * The nav's "Shop" used to leave the site for Patreon, where the products are
	 * described in the seller's own shape and a reader who did not already know
	 * what "premium" meant had no reason to click. This page is the storefront:
	 * one card per product, a picture, a price and a buy button, with the detail
	 * a click away instead of a domain away.
	 *
	 * Checkout stays on Patreon — nothing here takes money. The catalog is
	 * `static/data/shop.json`; see `$lib/shop`.
	 */
	import { onMount } from 'svelte';
	import { base } from '$app/paths';
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import ShopProductCard from '$lib/components/ShopProductCard.svelte';
	import ShopProductModal from '$lib/components/ShopProductModal.svelte';
	import { loadShop, visibleProducts, type ShopManifest, type ShopProduct } from '$lib/shop';
	import ArrowUpRight from '@lucide/svelte/icons/arrow-up-right';
	import Download from '@lucide/svelte/icons/download';
	import Heart from '@lucide/svelte/icons/heart';
	import ShoppingBag from '@lucide/svelte/icons/shopping-bag';

	const PATREON_SHOP = 'https://www.patreon.com/cw/krmani/shop';

	let manifest = $state<ShopManifest | null>(null);
	let loading = $state(true);
	let selected = $state<ShopProduct | null>(null);

	const products = $derived(visibleProducts(manifest));

	onMount(async () => {
		manifest = await loadShop();
		loading = false;
		// `?p=<id>` opens a product straight away, so one product can be linked
		// to and shared even though the detail is a dialog rather than a route.
		const id = page.url.searchParams.get('p');
		if (id) selected = products.find((prod) => prod.id === id) ?? null;
	});

	/** Keep the open product in the URL without adding a history entry. */
	function syncUrl(id: string | null) {
		try {
			const url = new URL(page.url);
			if (id) url.searchParams.set('p', id);
			else url.searchParams.delete('p');
			replaceState(url, {});
		} catch {
			// Navigation is unavailable before hydration; the dialog still opens.
		}
	}

	function open(product: ShopProduct) {
		selected = product;
		syncUrl(product.id);
	}

	function close() {
		selected = null;
		syncUrl(null);
	}

	const steps = [
		{
			icon: ShoppingBag,
			title: 'Buy on Patreon',
			body: 'Payment and delivery both happen there — this site never sees a card number.'
		},
		{
			icon: Download,
			title: 'Download the .apkg',
			body: 'The file is attached to the product post. Every purchase is a plain Anki package.'
		},
		{
			icon: Heart,
			title: 'Import and study',
			body: 'File → Import in Anki, on desktop or mobile. Audio, dictionary and stroke data ride inside the deck.'
		}
	];
</script>

<svelte:head>
	<title>Shop · Anki xiehanzi</title>
	<meta
		name="description"
		content="Premium Anki decks for Mandarin: HSK word decks with recognition and writing cards, a cloze sentence deck, the 214 Kangxi radicals, and print-ready PDFs."
	/>
</svelte:head>

<div class="mx-auto max-w-6xl px-5 py-12">
	<p class="font-mono text-xs uppercase tracking-[0.2em] text-neutral-400">Shop</p>
	<h1 class="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">Premium decks</h1>
	<p class="mt-3 max-w-2xl text-neutral-600">
		Prebuilt decks that go further than the free ones — separate recognition and writing cards, a
		redesigned card layout, a dictionary built into the review, and the paper editions. Buying one
		is what pays for the free decks, the deck creator and the tools.
	</p>

	{#if loading}
		<div class="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
			{#each [0, 1, 2] as n (n)}
				<div class="h-96 animate-pulse rounded-xl border border-neutral-200 bg-neutral-50"></div>
			{/each}
		</div>
	{:else if manifest}
		<div class="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
			{#each products as product (product.id)}
				<ShopProductCard {manifest} {product} onDetails={open} />
			{/each}
		</div>

		<p class="mt-6 text-sm text-neutral-500">
			Prices and checkout are on Patreon.
			<a
				href={manifest.shop || PATREON_SHOP}
				target="_blank"
				rel="noopener noreferrer"
				class="inline-flex items-center gap-1 underline"
			>
				See the whole shop <ArrowUpRight size={13} />
			</a>
		</p>
	{:else}
		<!-- No manifest is a normal state, not an error screen: point at the
		     storefront and get out of the way. -->
		<div class="mt-10 rounded-xl border border-neutral-200 p-6">
			<p class="text-sm text-neutral-600">The catalog could not be loaded.</p>
			<a
				href={PATREON_SHOP}
				target="_blank"
				rel="noopener noreferrer"
				class="mt-3 inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-wider text-neutral-900"
			>
				Open the shop on Patreon <ArrowUpRight size={13} />
			</a>
		</div>
	{/if}

	<!-- How a purchase reaches Anki. Buying a deck file is not the checkout most
	     people expect, so say it before they ask. -->
	<h2 class="mt-16 text-2xl font-bold tracking-tight">How it works</h2>
	<div class="mt-5 grid gap-4 sm:grid-cols-3">
		{#each steps as step (step.title)}
			<div class="rounded-xl border border-neutral-200 p-5">
				<h3 class="flex items-center gap-2 font-semibold">
					<step.icon size={16} />
					{step.title}
				</h3>
				<p class="mt-1.5 text-sm leading-relaxed text-neutral-600">{step.body}</p>
			</div>
		{/each}
	</div>

	<div class="mt-10 rounded-xl border border-neutral-200 bg-neutral-50 p-6">
		<h3 class="font-semibold">Not ready to buy?</h3>
		<p class="mt-1.5 max-w-2xl text-sm leading-relaxed text-neutral-600">
			Every HSK list is free to download, the 214 radicals build in your browser, and the deck
			creator turns your own words into a deck — no account, nothing to pay.
		</p>
		<div class="mt-3 flex flex-wrap gap-4">
			<a
				href="{base}/hsk"
				class="font-mono text-xs uppercase tracking-wider text-neutral-900 underline"
				>Free HSK decks</a
			>
			<a
				href="{base}/radicals"
				class="font-mono text-xs uppercase tracking-wider text-neutral-900 underline">Radicals</a
			>
			<a
				href="{base}/create"
				class="font-mono text-xs uppercase tracking-wider text-neutral-900 underline"
				>Deck creator</a
			>
		</div>
	</div>
</div>

{#if selected && manifest}
	<ShopProductModal {manifest} product={selected} onClose={close} />
{/if}

interface ShopifyAdminClient {
  graphql: (
    query: string,
    options?: { variables?: Record<string, unknown> },
  ) => Promise<Response>;
}

interface CreateDiscountInput {
  admin: ShopifyAdminClient;
  productTitle: string;
  shopifyProductId: string;
  discountPct: number;
}

export async function createAutomaticProductDiscount({
  admin,
  productTitle,
  shopifyProductId,
  discountPct,
}: CreateDiscountInput): Promise<string> {
  const mutation = `#graphql
    mutation CreateAutomaticBasicDiscount($automaticBasicDiscount: DiscountAutomaticBasicInput!) {
      discountAutomaticBasicCreate(automaticBasicDiscount: $automaticBasicDiscount) {
        automaticDiscountNode {
          id
        }
        userErrors {
          field
          message
        }
      }
    }
  `;

  const response = await admin.graphql(mutation, {
    variables: {
      automaticBasicDiscount: {
        title: `Discount Optimizer: ${productTitle} ${discountPct.toFixed(1)}%`,
        startsAt: new Date().toISOString(),
        combinesWith: {
          orderDiscounts: false,
          productDiscounts: false,
          shippingDiscounts: false,
        },
        customerGets: {
          value: {
            percentage: Number((discountPct / 100).toFixed(4)),
          },
          items: {
            products: {
              productsToAdd: [`gid://shopify/Product/${shopifyProductId}`],
            },
          },
        },
      },
    },
  });

  const payload = (await response.json()) as {
    data?: {
      discountAutomaticBasicCreate?: {
        automaticDiscountNode?: { id?: string };
        userErrors?: Array<{ message: string }>;
      };
    };
    errors?: Array<{ message: string }>;
  };

  if (payload.errors?.length) {
    throw new Error(payload.errors.map((error) => error.message).join("; "));
  }

  const result = payload.data?.discountAutomaticBasicCreate;
  if (result?.userErrors?.length) {
    throw new Error(result.userErrors.map((error) => error.message).join("; "));
  }

  const discountId = result?.automaticDiscountNode?.id;
  if (!discountId) {
    throw new Error("Shopify did not return a discount ID.");
  }

  return discountId;
}

import fetch from 'node-fetch';

const API_VERSION = 'v20230901';

export default async function createProductService(handle, token, headers = {}) {
  try {
    const url = `https://${handle}.myshopline.com/admin/openapi/${API_VERSION}/products/products.json`;
    const bodyParams = {
      product: {
        title: `shopline app test product`,
      },
    };
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'User-Agent': headers['user-agent'],
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(bodyParams),
    });
    if (!/2[0-9]+/.test(`${response.status}`)) {
      throw new Error(response.statusText);
    }
    const data = await response.json();
    return {
      headers: response.headers,
      data,
    };
  } catch (error) {
    throw error;
  }
}

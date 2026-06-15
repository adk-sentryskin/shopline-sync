import createProductService from '../../service/product/create';

export default async function createProductController(_req, res) {
  let status = 200;
  let error = null;
  let response;

  try {
    const { handle, accessToken } = res.locals.shopline.session;
    response = await createProductService(handle, accessToken, _req.headers);
  } catch (e) {
    console.log(`Failed to process products/create: ${e.message}`);
    status = 500;
    error = e.message;
  }
  res
    .status(status)
    .set({
      traceid: response.headers.get('traceid')?.split(',')?.[0],
    })
    .send({ success: status === 200, error, data: response.data });
}

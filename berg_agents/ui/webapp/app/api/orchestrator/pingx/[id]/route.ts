export async function GET(_r: Request, {params}: {params: Promise<{id: string}>}): Promise<Response> {
  const {id} = await params;
  return Response.json({got: id});
}

<?php
class ProductController
{
    public function actionView($id)
    {
        $product = Product::getById($id);
        if (!$product) {
            return $this->notFound();
        }
        return $this->render('product/view', ['product' => $product]);
    }

    public function actionList($category)
    {
        $products = Product::getByCategory($category);
        return $this->render('product/list', ['products' => $products]);
    }
}

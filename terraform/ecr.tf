resource "aws_ecr_repository" "inference" {
  name = "complaint-inference"

  # destroy otherwise fails while the repository holds images (section 38.2).
  force_delete = true

  # Re-pushing an existing tag is rejected at `docker push` instead of silently leaving
  # Lambda on the old digest (section 38, trap 3). Every change needs a new tag.
  image_tag_mutability = "IMMUTABLE"
}

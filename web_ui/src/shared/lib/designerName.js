// firstVIEW's designer names carry the season with them — "Yohji Yamamoto
// Ready To Wear Fall 2003" — which is fine on a results page and wrong in a
// list whose next line already says the season. This strips the tail back to
// the name.
//
// Shared rather than duplicated: the show list, the status bar and the page
// itself all have to agree on what a designer is called, and three copies of
// one regex is three chances for them to stop agreeing.
export function cleanDesignerName(fullName) {
  return fullName
    .replace(/\s+(Ready To Wear|Menswear|Couture|Men & Women)\s+.*/i, '')
    .replace(/\s+(Fall|Spring|Winter|Summer)\s+.*/i, '')
    .trim();
}

export default cleanDesignerName;

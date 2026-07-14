<?php
function pr($str)
{
  echo "$str<br>";
}

$date = htmlspecialchars($_GET["date"]);
$column1 = htmlspecialchars($_GET["column1"]);
$path = htmlspecialchars($_GET["path"]);
$suffix = htmlspecialchars($_GET["suffix"]);
$tbl_hdrs = htmlspecialchars($_GET["tbl_hdrs"]);
$baseline = htmlspecialchars($_GET["baseline"]);
$hdrs = explode(",", $tbl_hdrs);

function show_graph_subdirs($baseline, $path, $date, $suffix, $column1)
{
  $file_prefix = "/net/htdocs";
  $headers = [];
  $graphs = array_diff(scandir("$file_prefix/$path"), array(".", "..", "data"));
  foreach ($graphs as &$file) {
    if ((substr_compare($file, '.php', -4) != 0 ) &&
      (substr_compare($file, '.csh', -4) != 0 ) &&
      (substr_compare($file, '.log', -4) != 0 ) &&
      (substr_compare($file, '.err', -4) != 0 ) &&
      (substr_compare($file, '.out', -4) != 0 ) ) {
      if (empty($suffix)) {
        $newpath = "$path/$file";
      } else {
        $newpath = "$path/$file/$suffix";
      }
      if (substr_compare($file, '.pdf', -4) == 0 ) {
        $href ="$path/$file";
        $headers=["Graph Type", "Graph"];
      } else {
        $href = "?baseline=$baseline&tbl_hdrs=Graph%20Type,Graph%20Subtype&date=$date&column1=$file&path=$newpath";
      }

      echo "
      <tr>
        <td>
            <strong>$column1</strong>
        </td>
        <td>
          <a href=$href><strong> View </strong> $file</a><br>
        </td>
      </tr>";
    }
  }
  unset($file);
  return $headers;
}
?>

<!DOCTYPE html>
<html>
  <head>
    <title><?php echo $date; ?></title>
    <?php include('inc-meta.php'); ?>
  </head>
  <body class="ncar with-sidebar with-resources">
    <main class="container-lg py-2 pt-md-3">
      <div class="d-grid d-print-flex">
        <nav aria-label="breadcrumb" class="breadcrumb-wrapper mb-2 d-print-none">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="https://www.mmm.ucar.edu">MMM Home</a></li>
                <li class="breadcrumb-item active" aria-current="page">MPAS-JEDI Weekly Cycling</li>
            </ol>
        </nav>

        <article class="main-content-wrapper">
          <h2>MPAS-JEDI Weekly Cycling</h2>
          <h3><?php echo "$date vs $baseline"; ?></h3>

          <div class="main-content clearfix">
          <br>

          <!-- start of the dir list -->
          <table class="table">
            <tbody>
              <?php
                $new_hdrs = show_graph_subdirs($baseline, $path, $date, $suffix, $column1);
                if (count($new_hdrs) > 0) {
                  $hdrs = $new_hdrs;
                }
              ?>
            </tbody>
            <thead style="position: sticky; top: 0;">
              <tr>
              <th class="sticky-top" scope="col"><?php echo $hdrs[0]; ?></th>
              <th class="sticky-top" scope="col"><?php echo $hdrs[1]; ?></th>
              </tr>
            </thead>
          </table>
        </article>
        <?php include('inc-sidebar.php'); ?>
      </div>
    </main>
    <?php include('inc-js.php'); ?>
  </body>
</html>

